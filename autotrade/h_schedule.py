
import asyncio
import time
import requests
import json

from etf_strategy import check_signal
from etf_state import load_state as load_etf_state
from datetime import datetime, date
from telegram_log import log
from a_config import (
	TOKEN_TIME,
	NXT_TAKE_PROFIT_TIME,
	KRX_TAKE_PROFIT_TIME,
	MONITOR_START_TIME,
	FORCE_SELL_TIME,
	SEARCH_TIME,
	BUY_TIME,
	MORNING_CHECK_TIME,
	AFTERNOON_CHECK_TIME,
	BUY_CHECK_TIME,
	CANCEL_TAKE_PROFIT_TIME,
	ETF_FLOW_MAX_AGE_SECONDS,
)

from b_auth import get_token
from c0_buy_selector import get_buy_code
from d_account import get_account_summary
from e_state import load_state, save_state, clear_state

from f_order import (
	get_upper_price,
	buy,
	take_profit_nxt,
	take_profit_krx,
	market_sell,
	cancel_take_profit,
)

from g_websk import WebSocketClient
from i_healthcheck import process_check


ETF_CODES = {"069500", "114800"}


async def ensure_websocket(token, websocket):
	if token is None:
		token = get_token()

	if not token:
		log("★TOKEN")
		return None, None

	if websocket is None or not websocket.running:
		websocket = WebSocketClient(token)
		asyncio.create_task(websocket.run())

	elif websocket.token != token:
		websocket.token = token
		await websocket.disconnect()

	for _ in range(100):
		if websocket.connected:
			return websocket.token, websocket

		await asyncio.sleep(0.1)

	log("★WEBSK")
	return token, None


def sync_account_state(token, origin="existing"):
	"""
	실제 계좌 잔고를 기준으로 주도주 상태만 동기화한다.
	ETF 보유는 e_state.json에 기록하지 않는다.
	"""

	summary = get_account_summary(token)

	if summary.get("cash") is None:
		log("★ACCOUNT")
		return False

	state = load_state()

	lead_stock = summary.get("lead_stock_holding")
	etf_holding = summary.get("etf_holding")

	if etf_holding:
		print(
			"[ACCOUNT] ETF 보유 확인: "
			f"{etf_holding['code']} / {etf_holding['qty']}주"
		)

	if lead_stock is None:
		# 계좌에 주도주가 없으면 주도주 보유 정보만 정리한다.
		# 매수 후보와 미체결 매수 주문 정보는 보존한다.
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

	state["holding"] = True
	state["code"] = lead_stock["code"]
	state["name"] = lead_stock["name"]
	state["qty"] = lead_stock["qty"]
	state["buy_price"] = lead_stock["buy_price"]

	if origin:
		state["position_origin"] = origin

	save_state(state)

	print(
		"[ACCOUNT] 주도주 보유 동기화: "
		f"{lead_stock['code']} / {lead_stock['qty']}주"
	)

	return True


def check_program_history(token, stock_code="005930"):
	url = "https://api.kiwoom.com/api/dostk/mrkcond"

	headers = {
		"Content-Type": "application/json;charset=UTF-8",
		"authorization": f"Bearer {token}",
		"cont-yn": "N",
		"next-key": "",
		"api-id": "ka90008",
	}

	params = {
		"amt_qty_tp": "1",
		"stk_cd": stock_code,
		"date": datetime.now().strftime("%Y%m%d"),
	}

	all_rows = []
	page = 0
	seen_keys = set()

	while True:
		page += 1

		response = requests.post(
			url,
			headers=headers,
			json=params,
			timeout=15,
		)

		response.raise_for_status()
		result = response.json()

		if result.get("return_code") != 0:
			log(f"★HISTORY_API_{result}")
			break

		rows = result.get("stk_tm_prm_trde_trnsn", [])
		all_rows.extend(rows)

		cont_yn = response.headers.get("cont-yn", "N")
		next_key = response.headers.get("next-key", "")

		print(
			f"프로그램 매매 과거 조회 {page}페이지: "
			f"{len(rows)}건"
		)

		if cont_yn != "Y" or not next_key:
			break

		if next_key in seen_keys:
			print("중복 next-key 발견")
			break

		seen_keys.add(next_key)

		headers["cont-yn"] = "Y"
		headers["next-key"] = next_key

		if page >= 100:
			break

	all_rows.sort(key=lambda x: x.get("tm", ""))

	print("전체 조회 건수:", len(all_rows))

	if all_rows:
		print("가장 오래된 기록:", all_rows[0].get("tm"))
		print("가장 최근 기록:", all_rows[-1].get("tm"))

	with open("program_history.json", "w", encoding="utf-8") as f:
		json.dump(all_rows, f, ensure_ascii=False, indent=2)

	return all_rows

def read_live_program_flow(now):
    """
    실시간 삼성전자 프로그램 매매 수급을 읽는다.
    오늘 날짜의 최신 데이터이며 30초 이내인 경우에만 반환한다.
    """
    try:
        with open(
            "program_flow_live.json",
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

        if data.get("date") != now.strftime("%Y%m%d"):
            return None

        if data.get("stock_code") != "005930":
            return None

        if data.get("unit") != "백만원":
            return None

        flow_time = str(data.get("current_time") or "").strip()

        if len(flow_time) != 6 or not flow_time.isdigit():
            return None

        received_time = datetime.strptime(
            now.strftime("%Y%m%d") + flow_time,
            "%Y%m%d%H%M%S",
        )

        age = (now - received_time).total_seconds()

        if age < 0 or age > ETF_FLOW_MAX_AGE_SECONDS:
            return None

        net_amount = int(data.get("current_net_amount"))

		return {
		    "net_amount": net_amount,
		    "time": flow_time,
		    "high_net_amount": int(data.get("high_net_amount", net_amount)),
		    "low_net_amount": int(data.get("low_net_amount", net_amount)),
		}

    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def monitor_etf_signal(now, last_flow_signature):
    """
    실시간 수급이 새로 들어왔을 때만 ETF 전략을 실행한다.
    이 함수는 신호 판단과 상태 갱신만 하며 주문은 내지 않는다.
    """
    if not ("09:00:00" <= now.strftime("%H:%M:%S") < "15:20:00"):
        return last_flow_signature

    flow = read_live_program_flow(now)

    if flow is None:
        return last_flow_signature

	signature = (
		flow["time"],
		flow["net_amount"],
		flow["high_net_amount"],
		flow["low_net_amount"],
	)

    if signature == last_flow_signature:
        return last_flow_signature

	signal = check_signal(
	    flow["net_amount"],
	    flow["high_net_amount"],
	    flow["low_net_amount"],
	)

    if signal:
        log(
            f"ETF_SIGNAL_{signal}_"
            f"{flow['net_amount']}_{flow['time']}"
        )
        print(
            "[ETF 신호 감지 - 주문 미실행]",
            signal,
            flow["net_amount"],
            flow["time"],
        )

    return signature

async def main():
	token = None
	websocket = None
	last_date = date.today()
	last_etf_flow_signature = None
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
		"cancel_tp": False,
		"history_test": False,
		"websocket_started": False,
	}

	ACCOUNT_RETRY_INTERVAL = 5

	last_account_retry = {
		"token": 0.0,
		"search": 0.0,
	}

	while True:
		try:
			now = datetime.now()
			current = now.strftime("%H:%M:%S")
			# 실시간 ETF 수급 감시 및 신호 판단
			last_etf_flow_signature = monitor_etf_signal(
			    now,
			    last_etf_flow_signature,
			)
			if now.date() != last_date:
				last_date = now.date()
				token = None
				last_etf_flow_signature = None
				
				for key in executed:
					executed[key] = False

				last_account_retry = {
					"token": 0.0,
					"search": 0.0,
				}

				log(f"DAY_{now:%m%d}")

			if not executed["history_test"] and token is None:
				token = get_token()

			if (
				token
				and websocket is None
				and MORNING_CHECK_TIME <= current < CANCEL_TAKE_PROFIT_TIME
				and not executed["websocket_started"]
			):
				websocket = WebSocketClient(token)
				asyncio.create_task(websocket.run())
				executed["websocket_started"] = True
				print("BACKGROUND WEBSOCKET START REQUESTED")

			if not executed["history_test"] and token:
				await asyncio.to_thread(
					check_program_history,
					token,
					"005930",
				)

				executed["history_test"] = True
				print("삼성전자 과거 데이터 조회 테스트 완료")

			# 06:55 시스템 점검
			if (
				MORNING_CHECK_TIME <= current < TOKEN_TIME
				and not executed["morning_check"]
			):
				executed["morning_check"] = True

				token, websocket = await ensure_websocket(
					token,
					websocket,
				)

				if websocket is None:
					log("★WEBSK_MORNING")
				else:
					await process_check(token, websocket, "morning")

			# 07:00 토큰 및 계좌 준비
			if (
				TOKEN_TIME <= current < SEARCH_TIME
				and not executed["token"]
			):
				token = get_token()

				if not token:
					log("★TOKEN")

				else:
					if websocket is not None:
						websocket.token = token
						await websocket.disconnect()

					retry_now = time.monotonic()

					if (
						retry_now - last_account_retry["token"]
						>= ACCOUNT_RETRY_INTERVAL
					):
						last_account_retry["token"] = retry_now

						summary = get_account_summary(token)

						if summary.get("cash") is None:
							log("★ACCOUNT")

						else:
							executed["token"] = True

							sync_account_state(
								token,
								"existing",
							)

							if summary.get("etf_holding"):
								log("ETF_HOLDING_AT_START")

							print("[07:00] Trading preparation complete")

			# 07:30 조건 검색 및 후보 선정
			if (
				SEARCH_TIME <= current < NXT_TAKE_PROFIT_TIME
				and not executed["search"]
			):
				token, websocket = await ensure_websocket(
					token,
					websocket,
				)

				if websocket is None:
					log("★WEBSK_SEARCH")

				else:
					retry_now = time.monotonic()

					if (
						retry_now - last_account_retry["search"]
						>= ACCOUNT_RETRY_INTERVAL
					):
						last_account_retry["search"] = retry_now

						summary = get_account_summary(token)

						if summary.get("cash") is None:
							log("★ACCOUNT_SEARCH")

						else:
							executed["search"] = True

							sync_account_state(
								token,
								"existing",
							)

							state = load_state()

							if summary.get("has_holding"):
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
			if (
				NXT_TAKE_PROFIT_TIME <= current < KRX_TAKE_PROFIT_TIME
				and not executed["nxt_tp"]
			):
				executed["nxt_tp"] = True
				state = load_state()

				if (
					state.get("holding")
					and state.get("position_origin") == "existing"
				):
					order_no = take_profit_nxt(token)
					log("N_O" if order_no else "N_X")

			# 08:30 KRX 익절 주문
			if (
				KRX_TAKE_PROFIT_TIME <= current < MONITOR_START_TIME
				and not executed["krx_tp"]
			):
				executed["krx_tp"] = True
				state = load_state()

				if (
					state.get("holding")
					and state.get("position_origin") == "existing"
				):
					order_no = take_profit_krx(token)
					log("K_O" if order_no else "K_X")

			# 08:59:55 실시간 감시 준비
			if (
				MONITOR_START_TIME <= current < "09:00:10"
				and not executed["monitor"]
			):
				executed["monitor"] = True

				token, websocket = await ensure_websocket(
					token,
					websocket,
				)

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
			if (
				BUY_TIME <= current < "09:00:10"
				and not executed["buy"]
			):
				executed["buy"] = True

				token, websocket = await ensure_websocket(
					token,
					websocket,
				)

				if websocket is None:
					log("★WEBSK_BUY")

				else:
					state = load_state()
					summary = get_account_summary(token)

					if summary.get("cash") is None:
						log("★ACCOUNT_BUY")

					elif summary.get("has_holding"):
						log("SKIP_BUY_HOLDING")

					elif not state.get("candidate_code"):
						log("No_B")

					elif state.get("buy_order_no"):
						log("SKIP_BUY_ORDER_EXISTS")

					else:
						expected_price = websocket.price_data.get(
							"expected_price",
							0,
						)

						if expected_price <= 0:
							log("★EXPECTED_PRICE")

						else:
							buy_price = get_upper_price(
								expected_price * 1.01
							)

							order_no = buy(
								token,
								state["candidate_code"],
								buy_price,
							)

							log(
								f"O_{order_no}"
								if order_no
								else "★ORDER"
							)

			# 15:15 토큰 갱신 및 시스템 점검
			if (
				AFTERNOON_CHECK_TIME <= current < FORCE_SELL_TIME
				and not executed["afternoon_check"]
			):
				executed["afternoon_check"] = True

				new_token = get_token()

				if new_token:
					token = new_token

					if websocket is not None:
						websocket.token = token
						await websocket.reconnect()

				else:
					log("★TOKEN_REFRESH")

				await process_check(
					token,
					websocket,
					"afternoon",
				)

			# 15:25 기존 보유분 강제 매도
			if (
				FORCE_SELL_TIME <= current < "15:26:00"
				and not executed["force_sell"]
			):
				executed["force_sell"] = True
				state = load_state()

				if (
					state.get("holding")
					and state.get("position_origin") == "existing"
				):
					log("FORCE_EXISTING")
					order_no = market_sell(token)

					if not order_no:
						log("★FORCE_SELL")

				else:
					print("15:25: 신규 매수분은 익일까지 보유 가능")

			# 당일 매수 점검
			if (
				BUY_CHECK_TIME <= current < "08:56:00"
				and not executed["buy_check"]
			):
				executed["buy_check"] = True

				await process_check(
					token,
					websocket,
					"buy",
				)

			# 15:31 하루 마감 처리
			if (
				CANCEL_TAKE_PROFIT_TIME <= current < "15:32:00"
				and not executed["cancel_tp"]
			):
				executed["cancel_tp"] = True

				token, websocket = await ensure_websocket(
					token,
					websocket,
				)

				if websocket is None:
					log("★WEBSK_CANCEL_TAKE_PROFIT")

				else:
					state = load_state()

					if (
						state.get("take_profit_order_no")
						and state.get("position_origin") == "existing"
					):
						order_no = cancel_take_profit(token)

						if order_no:
							log("CANCEL_EXISTING_TP")
						else:
							log("★CANCEL_EXISTING_TP")

					await asyncio.sleep(2)

					summary = get_account_summary(token)

					if summary.get("cash") is None:
						log("★ACCOUNT")

					else:
						holding = (
							"O" if summary["has_holding"] else "X"
						)

						log(f"A_{summary['cash']}_{holding}")

					await websocket.stop()
					websocket = None

					print("WebSocket stopped for today")

			await asyncio.sleep(0.1)

		except Exception as e:
			log(f"★SCHEDULE_{type(e).__name__}")
			print("Schedule error:", e)
			await asyncio.sleep(1)


if __name__ == "__main__":
	asyncio.run(main())
