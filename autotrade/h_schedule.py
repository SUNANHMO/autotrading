
import asyncio
import time
from datetime import datetime, date
from telegram_log import log
from a_config import (TOKEN_TIME, NXT_TAKE_PROFIT_TIME, KRX_TAKE_PROFIT_TIME, MONITOR_START_TIME,
	FORCE_SELL_TIME, SEARCH_TIME, BUY_TIME, MORNING_CHECK_TIME, AFTERNOON_CHECK_TIME, BUY_CHECK_TIME,CANCEL_TAKE_PROFIT_TIME,)
from b_auth import get_token
from c0_buy_selector import get_buy_code
from d_account import get_account_summary
from e_state import load_state, save_state, clear_state
from f_order import (get_upper_price, buy, take_profit_nxt, take_profit_krx, market_sell,cancel_take_profit,)
from g_websk import WebSocketClient
from i_healthcheck import process_check

async def ensure_websocket(token, websocket):
	if token is None:
		token = get_token()
	if not token:
		log("★TOKEN")
		return None, None
	if websocket is None:
		websocket = WebSocketClient(token)
		asyncio.create_task(websocket.run())
		for _ in range(100):
			if websocket.connected:
				break
			await asyncio.sleep(0.1)
		if not websocket.connected:
			log("★WEBSK")
			return token, None
	token = websocket.token
	return token, websocket

def sync_account_state(token, origin="existing"):
	# 계좌를 기준으로 실제 보유 정보를 갱신한다. 후보 종목은 이 함수에서 지우거나 덮어쓰지 않는다.
	summary = get_account_summary(token)

	if summary.get("cash") is None:
		log("★ACCOUNT")
		return False

	state = load_state()

	if not summary["has_holding"]: # 매수 주문이 대기 중일 수 있으므로 계좌에 보유가 없다고 state 전체를 초기화하지 않는다.
		state["holding"] = False
		state["qty"] = 0
		state["buy_price"] = 0
		state["name"] = None
		state["buy_date"] = None
		state["position_origin"] = None
		state["take_profit_order_no"] = None
		state["profit_market"] = None
		state["sell_order_no"] = None
		save_state(state)
		return True

	stock = summary["holding"]

	state["holding"] = True
	state["code"] = stock["code"]
	state["name"] = stock["name"]
	state["qty"] = stock["qty"]
	state["buy_price"] = stock["buy_price"]

	if origin:
		state["position_origin"] = origin

	save_state(state)
	return True


async def main():
	token = None
	websocket = None
	last_date = date.today()

	# 작업 이름으로 관리한다. MONITOR_START_TIME과 BUY_TIME이 같은 시각이어도 충돌하지 않는다.
	executed = {
		"morning_check": False,
		"token": False,
		"search": False,
		"nxt_tp": False,
		"krx_tp": False,
		"monitor": False,
		"buy": False,
		"afternoon_check": False,
		"force_sell": False,
		"buy_check": False,
		"cancel_tp": False,}

	while True:
		try:
			now = datetime.now()
			current = now.strftime("%H:%M:%S")

			if now.date() != last_date:
				last_date = now.date()
				for key in executed:
					executed[key] = False
				log(f"DAY_{now:%m%d}")
	
			# 06:55 시스템 점검
			if (MORNING_CHECK_TIME <= current < TOKEN_TIME and not executed["morning_check"]):
				executed["morning_check"] = True
				token, websocket = await ensure_websocket(token, websocket)
				if websocket is None:
					log("★WEBSK_MORNING")
				else:
					await process_check(token, websocket, "morning")

			# 07:00 토큰 및 계좌 준비
			if (TOKEN_TIME <= current < SEARCH_TIME	and not executed["token"]):
				token = get_token()
				if not token:
					log("★TOKEN")
				else:
					executed["token"] = True
					summary = get_account_summary(token)
					if summary.get("cash") is None:
						log("★ACCOUNT")
					elif summary["has_holding"]:
						sync_account_state(token, "existing") # 아침부터 보유한 종목은 기존 보유분으로 표시한다.
					else:
						clear_state()
					print("[07:00] Trading preparation complete")

			# 07:30 조건 검색 및 후보 선정
			if (SEARCH_TIME <= current < NXT_TAKE_PROFIT_TIME and not executed["search"]):
				executed["search"] = True
				token, websocket = await ensure_websocket(token, websocket)
				if websocket is None:
					log("★WEBSK_SEARCH")
				else:
					summary = get_account_summary(token)
					if summary.get("cash") is None:
						log("★ACCOUNT_SEARCH")
					else:
						state = load_state()

						if summary["has_holding"]: # 기존 보유분이 있으면 신규 매수 후보는 선택하더라도 매수하지 않는다.
							sync_account_state(token, "existing")
							log("SKIP_SEARCH_HOLDING")
						else:
							codes = await websocket.search_condition()
							candidate = get_buy_code(token, codes)
							state = load_state()
							if candidate is None:
								state["candidate_code"] = None
								state["candidate_name"] = None
								save_state(state)
								log("No_B")
							else:
								state["candidate_code"] = candidate
								state["candidate_name"] = None
								save_state(state)

								await websocket.register_price(candidate)
								log(f"B_{candidate}")

			# 08:00 NXT 익절 주문
			if (NXT_TAKE_PROFIT_TIME <= current < KRX_TAKE_PROFIT_TIME and not executed["nxt_tp"]):
				executed["nxt_tp"] = True
				state = load_state()
				if (
					state.get("holding")
					and state.get("position_origin") == "existing"):
					order_no = take_profit_nxt(token)
					log("N_O" if order_no else "N_X")

			# 08:30 KRX 익절 주문
			if (KRX_TAKE_PROFIT_TIME <= current < MONITOR_START_TIME and not executed["krx_tp"]):
				executed["krx_tp"] = True
				state = load_state()

				if (
					state.get("holding")
					and state.get("position_origin") == "existing"):
					order_no = take_profit_krx(token)
					log("K_O" if order_no else "K_X")

			# 08:59:55 실시간 감시 준비
			if (MONITOR_START_TIME <= current < "09:00:10" and not executed["monitor"]):
				executed["monitor"] = True
				token, websocket = await ensure_websocket(token, websocket)

				if websocket is None:
					log("★WEBSK_MONITOR")
				else:
					state = load_state()
					codes = []
					if state.get("holding") and state.get("code"):
						codes.append(state["code"])
					if state.get("candidate_code"):
						codes.append(state["candidate_code"])
					await websocket.register_prices(codes)
					if codes:
						log(f"TR_{'_'.join(codes)}")
					else:
						log("No_H")

			# 08:59:55 신규 매수 주문
			if (BUY_TIME <= current < "09:00:10" and not executed["buy"]):
				executed["buy"] = True
				token, websocket = await ensure_websocket(token, websocket)

				if websocket is None:
					log("★WEBSK_BUY")
				else:
					state = load_state()
					summary = get_account_summary(token)

					if summary.get("cash") is None:
						log("★ACCOUNT_BUY")
					elif summary["has_holding"]:
						log("SKIP_BUY_HOLDING")
					elif not state.get("candidate_code"):
						log("No_B")
					elif state.get("buy_order_no"):
						log("SKIP_BUY_ORDER_EXISTS")
					else:
						expected_price = (websocket.price_data.get("expected_price", 0))

						if expected_price <= 0:
							log("★EXPECTED_PRICE")
						else:
							buy_price = get_upper_price(expected_price * 1.01)
							order_no = buy(token, state["candidate_code"], buy_price,)
							log(f"O_{order_no}"
								if order_no
								else "★ORDER")

			# 15:15 토큰 갱신 및 시스템 점검
			if (AFTERNOON_CHECK_TIME <= current < FORCE_SELL_TIME and not executed["afternoon_check"]):
				executed["afternoon_check"] = True
				new_token = get_token()
				if new_token:
					token = new_token
					if websocket is not None:
						websocket.token = token
						await websocket.reconnect()
				else:
					log("★TOKEN_REFRESH")
				await process_check(token, websocket, "afternoon")

			# 15:25 기존 보유분 강제 매도, 신규 매수분은 당일 강제 매도하지 않는다.
			if (FORCE_SELL_TIME <= current < "15:26:00" and not executed["force_sell"]):
				executed["force_sell"] = True
				state = load_state()

				if (state.get("holding") and state.get("position_origin") == "existing"):
					log("FORCE_EXISTING")
					order_no = market_sell(token)
					if not order_no:
						log("★FORCE_SELL")
				else:
					print("15:25: 신규 매수분은 익일까지 보유 가능")

			# 당일 매수 점검
			if (BUY_CHECK_TIME <= current < "08:56:00" and not executed["buy_check"]):
				executed["buy_check"] = True
				await process_check(token, websocket, "buy")
			await asyncio.sleep(0.1)

			# 15:31 하루 마감 처리
			if (CANCEL_TAKE_PROFIT_TIME <= current < "15:32:00"
					and not executed["cancel_tp"]):
				executed["cancel_tp"] = True
				token, websocket = await ensure_websocket(token, websocket)
				if websocket is None:
					log("★WEBSK_CANCEL_TAKE_PROFIT")
				else:
					state = load_state()
					# 기존 보유분의 익절 주문만 취소
					if (
						state.get("take_profit_order_no")
						and state.get("position_origin") == "existing"):
						order_no = cancel_take_profit(token)
						if order_no:
							log("CANCEL_EXISTING_TP")
						else:
							log("★CANCEL_EXISTING_TP")
					# 최종 계좌 상태 확인
					await asyncio.sleep(2)
					summary = get_account_summary(token)
					if summary.get("cash") is None:
						log("★ACCOUNT")
					else:
						holding = "O" if summary["has_holding"] else "X"
						log(f"A_{summary['cash']}_{holding}")
					# 당일 WebSocket 종료
					await websocket.stop()
					websocket = None
					print("WebSocket stopped for today")
					
		except Exception as e:
			log(f"★SCHEDULE_{type(e).__name__}")
			print("Schedule error:", e)
			await asyncio.sleep(1)

if __name__ == "__main__":
	asyncio.run(main())
