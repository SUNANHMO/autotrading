import asyncio
import time
from datetime import datetime, date
from telegram_log import log

from a_config import (BUY_PRICE_BUFFER_RATE, STOP_LOSS_RATE,
	TOKEN_TIME,	NXT_TAKE_PROFIT_TIME,KRX_TAKE_PROFIT_TIME,
	MONITOR_START_TIME,	FORCE_SELL_TIME, MONITOR_END_TIME,
	SEARCH_TIME, BUY_TIME, CANCEL_TAKE_PROFIT_TIME,
	MORNING_CHECK_TIME,AFTERNOON_CHECK_TIME,BUY_CHECK_TIME)
from b_auth import get_token
from c0_buy_selector import get_buy_code
from c2_program import is_trading_day
from d_account import get_account_summary
from e_state import load_state, save_state, clear_state, get_force_sell_date
from f_order import (get_upper_price, buy, should_force_sell,
	take_profit_nxt, take_profit_krx, cancel_take_profit, market_sell)
from g_websk import WebSocketClient
from i_healthcheck import process_check
last_date = date.today()

async def ensure_websocket(token, websocket):
	# 토큰 없으면 새로 발급
	if token is None:
		token = get_token()
		print("new token =", token)

	if not token:
		log("★TOKEN")
		return None, None

	# 웹소켓 없으면 새로 생성
	if websocket is None:
		websocket = WebSocketClient(token)
		asyncio.create_task(websocket.run())

		# 로그인 완료 대기 (최대 10초)
		for _ in range(100):
			if websocket.connected:
				break
			await asyncio.sleep(0.1)

		if not websocket.connected:
			log("★WEBSK")
			return token, None

		# 주문체결 등록
		await websocket.register_order()

	# 연결이 끊겼으면 재연결
	elif not websocket.connected:
		await websocket.reconnect()

	return token, websocket

async def main():
	global last_date
	token = None
	websocket = None
	# 하루에 한 번만 실행할 작업 체크용
	executed = {
		TOKEN_TIME: False,
		NXT_TAKE_PROFIT_TIME: False,
		KRX_TAKE_PROFIT_TIME: False,
		MONITOR_START_TIME: False,
		FORCE_SELL_TIME: False,
		MONITOR_END_TIME: False,
		SEARCH_TIME: False,
		BUY_TIME: False,
		CANCEL_TAKE_PROFIT_TIME: False,
		MORNING_CHECK_TIME: False,
		AFTERNOON_CHECK_TIME: False,
		BUY_CHECK_TIME: False}

	while True:
		try:
			now = datetime.now()
			# 날짜가 바뀌면 실행 여부 초기화
			if now.date() != last_date:
				last_date = now.date()
				for key in executed:
					executed[key] = False
				log(f"DAY_{now:%m%d}") #새로운 거래일 시작
			current = now.strftime("%H:%M:%S")
			
			# 이상감지
			if (
				websocket
				and MONITOR_START_TIME <= current < SEARCH_TIME):
				if time.time() - websocket.last_alive > 30:
					log("★WEBSK_ERROR")
					await websocket.reconnect()

			# 06:55 시스템 점검
			if (MORNING_CHECK_TIME <= current < TOKEN_TIME and not executed[MORNING_CHECK_TIME]):
				executed[MORNING_CHECK_TIME] = True
				token, websocket = await ensure_websocket(token, websocket)
				if websocket is None:
					log("★WEBSK_MORNING_CHECK_TIME")
					continue
				await process_check(token, websocket, "morning")

			# 07:00:00 토큰 확인, 계좌조회
			if (TOKEN_TIME <= current < NXT_TAKE_PROFIT_TIME and not executed[TOKEN_TIME]):
			
				if token is None:
					token = get_token()

				if not token:
					await asyncio.sleep(5)
					continue

				executed[TOKEN_TIME] = True
				print("[07:00] Starting Trading Preparation")

				summary = get_account_summary(token)
				state = load_state()

				if summary["has_holding"]:
					stock = summary["holding"]

					state["holding"] = True
					state["code"] = stock["code"]
					state["name"] = stock["name"]
					state["qty"] = stock["qty"]
					state["buy_price"] = stock["buy_price"]
					state["sell_order_no"] = None

					# 기존 state에 force_sell_date가 없을 경우 보완
					if not state.get("force_sell_date"):
						buy_date = datetime.today()
						force_sell_date = get_force_sell_date(buy_date)
						state["buy_date"] = buy_date.strftime("%Y%m%d")
						state["force_sell_date"] = force_sell_date.strftime("%Y%m%d")
					save_state(state)

				else:
					clear_state()

				print(f"Estimated Balance: {summary['cash']}")
				print(f"Purchase Amount: {summary['asset']}")
				print(f"Holding Status: {summary['has_holding']}")
				print("[07:00] Trading Preparation Completed")

			# 08:00:01 NXT 익절주문
			if (NXT_TAKE_PROFIT_TIME <= current < KRX_TAKE_PROFIT_TIME and not executed[NXT_TAKE_PROFIT_TIME]):
				executed[NXT_TAKE_PROFIT_TIME] = True
				state = load_state()
				if state["holding"]:
					print("[08:00] NXT Take-Profit Order")  # [08:00] NXT 익절주문
					order_no = take_profit_nxt(token)
					if order_no:
						log("N_O")
						print(order_no)
					else:
						log("N_X")

			# 08:30:01 KRX 익절주문
			if (KRX_TAKE_PROFIT_TIME <= current < MONITOR_START_TIME and not executed[KRX_TAKE_PROFIT_TIME]):
				executed[KRX_TAKE_PROFIT_TIME] = True
				state = load_state()
				if state["holding"]:
					print("[08:30] KRX Take-Profit Order")  # [08:30] KRX 익절주문
					order_no = take_profit_krx(token)
					if order_no:
						log("K_O")
						print(order_no)
					else:
						log("K_X")

			# 09:00:00 감시 시작
			if (MONITOR_START_TIME <= current < SEARCH_TIME and not executed[MONITOR_START_TIME]):
				executed[MONITOR_START_TIME] = True
				token, websocket = await ensure_websocket(token, websocket)
				if websocket is None:
					log("★WEBSK_MONITOR_START_TIME")
					continue
				print("[09:00] Starting Real-time Monitoring")
				state = load_state()
				if state["holding"]:
					await websocket.register_price(state["code"])
					log(f"TR_{state['code']}")
				else:
					log("No_H")

			# 15:15 시스템 점검
			if (AFTERNOON_CHECK_TIME <= current < FORCE_SELL_TIME and not executed[AFTERNOON_CHECK_TIME]):
				executed[AFTERNOON_CHECK_TIME] = True
				await process_check(token, websocket, "afternoon")

			# 15:19:00
			if (FORCE_SELL_TIME <= current < SEARCH_TIME and not executed[FORCE_SELL_TIME]):
				executed[FORCE_SELL_TIME] = True
				state = load_state()
				if state["holding"] and should_force_sell(token):
					log("FORCE")  # 비정상 보유 → 강제청산
					print("Calling market_sell function")  # 시장가매도 함수 호출
					order_no = market_sell(token)
					print(f"market_sell Return Value: {order_no}")  # market_sell 반환값 :
					if order_no:
						print("Force Liquidation Order Placed")  # 강제청산 주문
						
			# 15:20:05 검색
			if (SEARCH_TIME <= current < BUY_TIME and not executed[SEARCH_TIME]):
				executed[SEARCH_TIME] = True
				summary = get_account_summary(token)
				holding = summary["has_holding"]

				if not holding:
					clear_state()
					print("No Holding - State Cleared")
				else:
					print("Holding exists - Keep State")

				log("PGM")

				token, websocket = await ensure_websocket(token, websocket)
				if websocket is None:
					log("★WEBSK_SEARCH_TIME")
					continue

				codes = await websocket.search_condition()
				buy_code = get_buy_code(token, codes)

				if buy_code is None:
					log("No_B")
				else:
					if holding:
						log(f"SKIP_{buy_code}") # 보유중이면 기록만
					else:
						state = load_state()
						state["code"] = buy_code
						save_state(state)
						await websocket.register_price(buy_code)
						log(f"B_{buy_code}")
			
			# 15:25 시스템 점검
			if (BUY_CHECK_TIME <= current < BUY_TIME and not executed[BUY_CHECK_TIME]):
				executed[BUY_CHECK_TIME] = True
				await process_check(token, websocket, "buy")

			# 15:29:59 매수
			if (BUY_TIME <= current < CANCEL_TAKE_PROFIT_TIME and not executed[BUY_TIME]):
				executed[BUY_TIME] = True
				websocket = await ensure_websocket(token, websocket)
				if websocket is None:
					log("★WEBSK_BUY_TIME")
					continue
				state = load_state()
				# 이미 보유중이면 매수 금지
				if state["holding"]:
					log("SKIP_BUY")
				else:
					expected_price = websocket.price_data["expected_price"]
					if expected_price <= 0:
						log("★E")
					else:
						buy_price = get_upper_price(
							expected_price * (1 + BUY_PRICE_BUFFER_RATE))
						order_no = buy(token, state["code"], buy_price)
						if order_no:
							print(f"O_{order_no}")
						else:
							log("★ORDER")

			# 15:31:00
			if (CANCEL_TAKE_PROFIT_TIME <= current < "20:00:00" and not executed[CANCEL_TAKE_PROFIT_TIME]):
				executed[CANCEL_TAKE_PROFIT_TIME] = True
				state = load_state()
				if state.get("take_profit_order_no"):
					order_no = cancel_take_profit(token)

					if order_no:
						print("CANCEL")
					else:
						log("★CANCEL")
				# 하루 최종 계좌 상태
				summary = get_account_summary(token)
				if summary["cash"] is None:
					log("★ACCOUNT")
				else:
					holding = "O" if summary["has_holding"] else "X"
					log(f"A_{summary['cash']}_{holding}")

			# 실시간 손절 감시 (09:00 ~ 15:20까지만)
			if (
				websocket
				and MONITOR_START_TIME <= current < SEARCH_TIME
				and websocket.stop_loss_triggered
			):
				websocket.stop_loss_triggered = False
				state = load_state()
				if state["holding"] and state["sell_order_no"] is None:
					log("CUT") #[손절] 조건 충족
					order_no = market_sell(token)
					if order_no:
						print(f"S_{order_no}") #시장가 매도 주문

			await asyncio.sleep(1)

		except Exception as e:
			log("★Scheduler")
			print(e)
			await asyncio.sleep(5)

if __name__ == "__main__":
	asyncio.run(main())
