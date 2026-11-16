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
	ETF_FLOW_MAX_AGE_SECONDS,)
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
	cancel_take_profit,)
from g_websk import WebSocketClient
from etf_execution import (
	start_etf_initial_buy,
	start_etf_switch,
	advance_etf_switch,)
from i_healthcheck import process_check
from etf_recovery_check import check_etf_recovery
from etf_step11_diagnostic import diagnose_etf_recovery


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
	"""전체 페이지와 수급 금액을 검증한 뒤에만 과거 데이터를 저장한다."""
	import os
	import tempfile
	from etf_recovery import parse_amount

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
	seen_keys = set()
	seen_times = {}
	duplicate_count = 0
	completed = False
	max_pages = 100

	try:
		for page in range(1, max_pages + 1):
			response = requests.post(
				url, headers=headers, json=params, timeout=15,
			)
			response.raise_for_status()
			result = response.json()

			if not isinstance(result, dict) or str(result.get("return_code")) != "0":
				raise ValueError(f"API 응답 오류: {result}")

			rows = result.get("stk_tm_prm_trde_trnsn")
			if not isinstance(rows, list):
				raise ValueError(f"{page}페이지 데이터 형식 오류")

			for row in rows:
				if not isinstance(row, dict):
					raise ValueError(f"{page}페이지 행 형식 오류")

				tm = str(row.get("tm", "")).strip()
				if len(tm) != 6 or not tm.isdigit():
					raise ValueError(f"잘못된 수급 시간: {tm!r}")
				try:
					datetime.strptime(tm, "%H%M%S")
				except ValueError as exc:
					raise ValueError(f"유효하지 않은 수급 시간: {tm}") from exc

				try:
					net = parse_amount(row["prm_netprps_amt"])
					buy_amt = parse_amount(row["prm_buy_amt"])
					sell_amt = parse_amount(row["prm_sell_amt"])
				except (KeyError, TypeError, ValueError) as exc:
					raise ValueError(f"{tm} 수급 금액 파싱 실패") from exc

				if buy_amt < 0 or sell_amt < 0 or net != buy_amt - sell_amt:
					raise ValueError(f"{tm} 순매수 금액 불일치")

				if row.get("date") not in (None, "", params["date"]):
					raise ValueError(f"{tm} 조회 날짜 불일치")
				if row.get("stk_cd") not in (None, "", stock_code):
					raise ValueError(f"{tm} 종목코드 불일치")

				# 키움 연속조회에서 동일 시각의 동일 행이 반복될 수 있다.
				# 완전히 동일한 행만 제거하고, 같은 시각에 값이 다르면 중단한다.
				if tm in seen_times:
					if row != seen_times[tm]:
						raise ValueError(
							f"동일 시각 수급 내용 불일치: {tm}, "
							f"이전={seen_times[tm]}, 현재={row}"
						)
					duplicate_count += 1
					continue

				seen_times[tm] = row
				all_rows.append(row)
			cont_yn = str(response.headers.get("cont-yn", "N")).strip().upper()
			next_key = str(response.headers.get("next-key", "")).strip()
			print(f"프로그램 매매 과거 조회 {page}페이지: {len(rows)}건")

			if cont_yn == "N":
				completed = True
				break
			if cont_yn != "Y" or not next_key:
				raise ValueError(f"{page}페이지 연속조회 헤더 오류")
			if next_key in seen_keys:
				raise ValueError(f"{page}페이지 next-key 중복")
			seen_keys.add(next_key)
			headers["cont-yn"] = "Y"
			headers["next-key"] = next_key

		if not completed:
			raise ValueError(f"{max_pages}페이지 내 조회 미완료")
		if not all_rows:
			raise ValueError("과거 수급 데이터가 비어 있음")

		all_rows.sort(key=lambda row: row["tm"])
		# 장중 조회 결과는 09:00 부근부터 현재까지 충분히 최신이어야 한다.
		now = datetime.now()
		current = now.strftime("%H%M%S")
		if "090100" <= current < "152000":
			market_rows = [row for row in all_rows if "090000" <= row["tm"] <= current]
			if not market_rows or market_rows[0]["tm"] > "090100":
				raise ValueError("09:00 시작 수급 기록 누락")
			latest_dt = datetime.strptime(
				now.strftime("%Y%m%d") + market_rows[-1]["tm"], "%Y%m%d%H%M%S",
			)
			age = (now - latest_dt).total_seconds()
			if not 0 <= age <= 180:
				raise ValueError(f"과거 수급 최신성 부족: {age:.0f}초")
		# 검증된 결과만 임시 파일에 기록하고 원자적으로 교체한다.
		output = os.path.abspath("program_history.json")
		tmp_path = None
		try:
			with tempfile.NamedTemporaryFile(
				mode="w", encoding="utf-8", dir=os.path.dirname(output),
				prefix=".program_history_", suffix=".tmp", delete=False,
			) as file:
				tmp_path = file.name
				json.dump(all_rows, file, ensure_ascii=False, indent=2)
				file.flush()
				os.fsync(file.fileno())
			os.replace(tmp_path, output)
		except Exception:
			if tmp_path and os.path.exists(tmp_path):
				os.unlink(tmp_path)
			raise

		print(f"과거 수급 검증 완료: {len(all_rows)}건, "
			  f"중복 제거 {duplicate_count}건, "
			  f"{all_rows[0]['tm']} ~ {all_rows[-1]['tm']}")
		return all_rows

	except (requests.RequestException, ValueError, TypeError, OSError) as exc:
		log(f"★HISTORY_INVALID_{type(exc).__name__}")
		print(f"[과거 수급 조회 실패] 기존 파일 유지: {exc}")
		return None

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


async def monitor_etf_signal(now, last_flow_signature, token, websocket):
	"""
	새 실시간 수급 데이터가 들어왔을 때 ETF 신호를 판단한다.
	전환 신호만 주문 실행 모듈로 전달한다.
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
		flow["low_net_amount"],)

	if signature == last_flow_signature:
		return last_flow_signature

	signal = check_signal(
		flow["net_amount"],
		flow["high_net_amount"],
		flow["low_net_amount"],)

	if signal:
		log(
			f"ETF_SIGNAL_{signal}_"
			f"{flow['net_amount']}_{flow['time']}")

		print(
			"[ETF 신호 감지]",
			signal,
			flow["net_amount"],
			flow["time"],)

		if signal in ("BUY_KODEX200", "BUY_INVERSE"):
			if not token:
				log("★ETF_INITIAL_BUY_NO_TOKEN")
			else:
				started = await asyncio.to_thread(
					start_etf_initial_buy,
					token,
					signal,
					websocket,
				)
		
				if started:
					print(f"ETF_INITIAL_BUY_STARTED_{signal}")
				else:
					print(f"ETF_INITIAL_BUY_NOT_STARTED_{signal}")
		
		elif signal in ("SWITCH_TO_KODEX200", "SWITCH_TO_INVERSE"):
			if not token:
				log("★ETF_SWITCH_NO_TOKEN")
			else:
				started = await asyncio.to_thread(
					start_etf_switch,
					token,
					signal,
					websocket,
				)
		
				if started:
					print(f"ETF_SWITCH_SELL_STARTED_{signal}")
				else:
					print(f"ETF_SWITCH_SELL_NOT_STARTED_{signal}")

	return signature

async def main():
    token = None
    websocket = None

    # ETF 복구 기능 완성 전에는 자동 주문 차단
    etf_recovery_completed = False

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
        "recovery_check_logged": False,
        "websocket_started": False,
    }

    ACCOUNT_RETRY_INTERVAL = 5
    ETF_HISTORY_RETRY_INTERVAL = 60
    last_etf_history_attempt = 0.0

    last_account_retry = {
        "token": 0.0,
        "search": 0.0,
    }

    while True:
        try:
            now = datetime.now()
            current = now.strftime("%H:%M:%S")
            # ETF 복구 완료 전에는 ETF 주문 및 신호 판단 차단
            if etf_recovery_completed:
                if token and "09:00:00" <= current < "15:20:00":
                    await asyncio.to_thread(
                        advance_etf_switch,
                        token,
                        websocket,
                    )

                last_etf_flow_signature = await monitor_etf_signal(
                    now,
                    last_etf_flow_signature,
                    token,
                    websocket,
                )
            if now.date() != last_date:
                last_date = now.date()
                token = None
                last_etf_flow_signature = None
                etf_recovery_completed = False
                last_etf_history_attempt = 0.0
                
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

            # 장중 과거 수급 조회: 실패 또는 오래된 기록이면 완료 처리하지 않는다.
            # 이 검사는 ETF 주문 차단을 해제하지 않는다.
            if (
                token
                and "09:01:00" <= current < "15:20:00"
                and not executed["history_test"]
                and time.monotonic() - last_etf_history_attempt
                    >= ETF_HISTORY_RETRY_INTERVAL
            ):
                last_etf_history_attempt = time.monotonic()
                history_rows = await asyncio.to_thread(
                    check_program_history, token, "005930",
                )

                if history_rows:
                    market_rows = [
                        row for row in history_rows
                        if "090000" <= row["tm"] <= current.replace(":", "")
                    ]
                    if market_rows:
                        first_time = market_rows[0]["tm"]
                        latest_time = market_rows[-1]["tm"]
                        latest_dt = datetime.strptime(
                            now.strftime("%Y%m%d") + latest_time,
                            "%Y%m%d%H%M%S",
                        )
                        age = (now - latest_dt).total_seconds()
                        if first_time <= "090100" and 0 <= age <= 180:
                            executed["history_test"] = True
                            print("ETF 과거 수급 최신성 검사 통과 (주문 차단 유지)")
                            # 6단계: 읽기 전용 계좌 대조. 결과가 승인이라도 주문 차단은 해제하지 않는다.
                            if not executed["recovery_check_logged"]:
                                executed["recovery_check_logged"] = True
                                try:
                                    recovery_result = await asyncio.to_thread(
                                        check_etf_recovery, token,
                                    )
                                    replay = recovery_result.get("replay") or {}
                                    print("[ETF 복구 검사]")
                                    print(f"가상 포지션: {replay.get('position', '조회 불가')}")
                                    print(f"실제 포지션: {recovery_result.get('account_position')}")
                                    print(f"실제 보유수량: {recovery_result.get('account_qty')}")
                                    print(f"ETF 미체결: {recovery_result.get('unfilled_count')}")
                                    for order_index, order_info in enumerate(recovery_result.get("unfilled_details") or [], 1):
                                        print(
                                            f"[ETF 미체결 상세 {order_index}] "
                                            f"종목={order_info['code']}({order_info['name']}), "
                                            f"주문번호={order_info['order_no'] or '미제공'}, "
                                            f"주문수량(원본)={order_info['order_qty_raw'] if order_info['order_qty_raw'] is not None else '미제공'}, "
                                            f"미체결수량={order_info['remaining_qty']}, "
                                            f"매수매도구분(원본)={order_info['side_raw'] or '미제공'}, "
                                            f"거래소(원본)={order_info['market_raw'] or '미제공'}"
                                        )
                                    print(f"복구 승인 판정(주문 차단 유지): {recovery_result.get('approved') is True}")
                                    print(f"사유: {recovery_result.get('reason')}")
                                    # 11단계: 실제 주문 없이 8~10단계 진단 연결.
                                    try:
                                        step11 = await asyncio.to_thread(
                                            diagnose_etf_recovery, recovery_result,
                                        )
                                        print("[ETF 11단계 통합 진단 — 주문 차단 유지]")
                                        print(f"상태: {step11['status']}")
                                        print(f"계좌 정합성: {(step11.get('reconciliation') or {}).get('alignment')}")
                                        print(f"다음 검증: {step11['next_check']}")
                                        print(f"사유: {step11['reason']}")
                                    except Exception as diag_exc:
                                        print(f"[ETF 11단계 진단 보류] {type(diag_exc).__name__}: {diag_exc}")
                                except Exception as recovery_exc:
                                    log(f"★ETF_RECOVERY_CHECK_{type(recovery_exc).__name__}")
                                    print(f"[ETF 복구 검사 실패] {type(recovery_exc).__name__}: {recovery_exc}")
                        else:
                            log("★ETF_HISTORY_STALE_OR_INCOMPLETE")
                            print(f"[ETF 과거 수급 미완료] 최초={first_time}, 최신={latest_time}, 지연={age:.0f}초")
                    else:
                        log("★ETF_HISTORY_NO_MARKET_ROWS")

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
