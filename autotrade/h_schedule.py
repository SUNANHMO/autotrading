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
from e_state import load_state, save_state, clear_state
from f_order import (get_upper_price, buy, should_force_sell,
	take_profit_nxt, take_profit_krx, cancel_take_profit, market_sell)
from g_websk import WebSocketClient
from i_healthcheck import process_check
last_date = date.today()

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
				and MONITOR_START_TIME <= current < MONITOR_END_TIME):
				if time.time() - websocket.last_alive > 30:
					log("★WEBSK") #웹소켓 이상 감지
					await websocket.reconnect()

			# 06:55 시스템 점검
			if current >= MORNING_CHECK_TIME and not executed[MORNING_CHECK_TIME]:
				executed[MORNING_CHECK_TIME] = True
				token = get_token()
				websocket = WebSocketClient(token)
				asyncio.create_task(websocket.run())

				# 최대 10초 대기
				for _ in range(100):
					if websocket.connected:
						break
					await asyncio.sleep(0.1)
				if not websocket.connected:
					log("★WEBSK") # WebSocket 연결 실패 (06:55)
				else:
					await process_check(token, websocket, "morning")

			# 15:15 시스템 점검
			if current >= AFTERNOON_CHECK_TIME and not executed[AFTERNOON_CHECK_TIME]:
				executed[AFTERNOON_CHECK_TIME] = True
				await process_check(token, websocket, "afternoon")

			# 15:25 시스템 점검
			if current >= BUY_CHECK_TIME and not executed[BUY_CHECK_TIME]:
				executed[BUY_CHECK_TIME] = True
				await process_check(token, websocket, "buy")

# 07:00:00 토큰발급, 계좌확인
			if current >= TOKEN_TIME and not executed[TOKEN_TIME]:
				executed[TOKEN_TIME] = True
				print("[07:00] Starting Trading Preparation")  # [07:00] 거래 준비 시작

				summary = get_account_summary(token)
				state = load_state()
				today = datetime.today().strftime("%Y%m%d")

				if summary["has_holding"]:
					stock = summary["holding"]
					old_code = state["code"]

					state["holding"] = True
					state["code"] = stock["code"]
					state["name"] = stock["name"]
					state["qty"] = stock["qty"]
					state["buy_price"] = stock["buy_price"]
					state["sell_order_no"] = None

					if old_code == stock["code"]:

						if (
							is_trading_day(token)
							and state["last_holding_update"] != today
						):
							state["holding_days"] += 1
							state["last_holding_update"] = today

					else:
						state["holding_days"] = 1
						state["last_holding_update"] = today

					save_state(state)

				else:
					clear_state()
					state = load_state()

				print(f"Estimated Balance: {summary['cash']}")  # 추정자산 :
				print(f"Purchase Amount: {summary['asset']}")  # 매입금액 :
				print(f"Holding Status: {summary['has_holding']}")  # 보유여부 :
				print("[07:00] Trading Preparation Completed")  # [07:00] 거래 준비 완료
				
			# 08:00:01 NXT 익절주문
			if current >= NXT_TAKE_PROFIT_TIME and not executed[NXT_TAKE_PROFIT_TIME]:
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
			if current >= KRX_TAKE_PROFIT_TIME and not executed[KRX_TAKE_PROFIT_TIME]:
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
			if current >= MONITOR_START_TIME and not executed[MONITOR_START_TIME]:
				executed[MONITOR_START_TIME] = True
				print("[09:00] Starting Real-time Monitoring")  # [09:00] 실시간 감시 시작
				state = load_state()
				if state["holding"]:
					await websocket.register_price(state["code"])   # 보유종목 현재가 수신
					await websocket.register_order()				# 주문체결 수신
					log(f"TR_{state['code']}")
				else:
					log("No_H")

			# 15:19:00
			if current >= FORCE_SELL_TIME and not executed[FORCE_SELL_TIME]:
				executed[FORCE_SELL_TIME] = True
				if should_force_sell(token):
					log("FORCE")  # 비정상 보유 → 강제청산
					print("Calling market_sell function")  # 시장가매도 함수 호출
					order_no = market_sell(token)
					print(f"market_sell Return Value: {order_no}")  # market_sell 반환값 :
					if order_no:
						print("Force Liquidation Order Placed")  # 강제청산 주문
						
			# 15:20:05 검색
			if current >= SEARCH_TIME and not executed[SEARCH_TIME]:
				executed[SEARCH_TIME] = True
				log("PGM") #[15:20:05] 종목 검색 시작
				
				if not websocket.connected:
					await websocket.reconnect()

				codes = await websocket.search_condition()
				buy_code = get_buy_code(token, codes)
				if buy_code is None:
					log("No_B") #매수 후보 없음
				else:
					state = load_state()
					state["code"] = buy_code
					save_state(state)
					await websocket.register_price(buy_code)
					log(f"B_{buy_code}") #매수 후보 등록

			# 15:29:59 매수
			if current >= BUY_TIME and not executed[BUY_TIME]:
				executed[BUY_TIME] = True
				state = load_state()
				expected_price = websocket.price_data["expected_price"]
				if expected_price <= 0:
					log("★E") #예상체결가 수신 실패
				else:
					buy_price = get_upper_price(expected_price * (1 + BUY_PRICE_BUFFER_RATE))
					order_no = buy(token, state["code"], buy_price)
					if order_no:
						print(f"O_{order_no}") #매수주문 완료 : 
					else:
						log("★ORDER") #매수주문 실패

			# 15:31:00
			if current >= CANCEL_TAKE_PROFIT_TIME and not executed[CANCEL_TAKE_PROFIT_TIME]:
				executed[CANCEL_TAKE_PROFIT_TIME] = True
				order_no = cancel_take_profit(token)
				if order_no:
					print("CANCEL") #익절취소 완료
				else:
					log("★CANCEL") #익절취소 실패
				# 하루 최종 계좌 상태
				summary = get_account_summary(token)
				holding = "O" if summary["has_holding"] else "X"
				log(f"A_{summary['cash']}_{holding}")

			# 실시간 손절 감시 (09:00 ~ 15:20까지만)
			if websocket.stop_loss_triggered:
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