import asyncio
import time
import requests
import json

from kospi_ma20_filter import refresh_kospi_ma20_gate, read_kospi_ma20_gate
from lead_candidate_history import save_candidate_history
from etf_history_archive import archive_program_history
from market_program_archive import collect_today
from etf_live_scheduler import EtfLiveScheduler
from datetime import datetime, date
from telegram_log import log
from a_config import (
	TOKEN_TIME,
	LEAD_TRADING_ENABLED,
	LEAD_KOSPI_MA20_ENABLED,
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
	MONITOR_END_TIME,
	shift_time,
	relative_time,
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
	cancel_take_profit,)
from g_websk import WebSocketClient
from i_healthcheck import process_check




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


def sync_account_state(token, origin="existing", summary=None):
	"""
	실제 계좌 잔고를 기준으로 주도주 상태만 동기화한다.
	ETF 보유는 e_state.json에 기록하지 않는다.
	"""

	if summary is None:
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


_history_alerts = set()
_history_alert_day = None


def history_alert_once(message):
	global _history_alert_day
	today = date.today()
	if _history_alert_day != today:
		_history_alerts.clear()
		_history_alert_day = today
	if message not in _history_alerts:
		_history_alerts.add(message)
		log(message)


def check_program_history(token, stock_code="005930", *, persist_live=True):
	"""전체 페이지와 수급 금액을 검증한 뒤에만 과거 데이터를 저장한다."""
	import os
	import tempfile
	from c2_program import parse_amount

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

	if date.today().weekday() >= 5:
		print("[수급 조회 생략] 주말")
		return None

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
				# 보관용 조회는 전체 페이지를 요청하되 저장 범위 밖 행은 제외한다.
				# 실시간 전략의 엄격한 검증 방식은 변경하지 않는다.
				if not persist_live and len(tm) == 6 and tm.isdigit() and not (KRX_TAKE_PROFIT_TIME.replace(":", "") <= tm <= CANCEL_TAKE_PROFIT_TIME.replace(":", "")):
					continue
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

				# 일반 거래량 등의 차이는 허용하되 프로그램 금액 충돌은 거부.
				if tm in seen_times:
					previous = seen_times[tm]
					fields = ("prm_netprps_amt", "prm_buy_amt", "prm_sell_amt")
					if any(parse_amount(previous[k]) != parse_amount(row[k]) for k in fields):
						raise ValueError(f"동일 시각 프로그램 금액 불일치: {tm}")
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
			# 장 마감 보관용 전체 이력 조회: 페이지 요청 간 0.5초 대기
			if not persist_live:
				time.sleep(0.5)

		if not completed:
			raise ValueError(f"{max_pages}페이지 내 조회 미완료")
		if not all_rows:
			raise ValueError("과거 수급 데이터가 비어 있음")

		if not persist_live:
			all_rows = list(seen_times.values())
		all_rows.sort(key=lambda row: row["tm"])
		# 장중 조회 결과는 09:00 부근부터 현재까지 충분히 최신이어야 한다.
		now = datetime.now()
		current = now.strftime("%H%M%S")
		if relative_time(MONITOR_START_TIME, 65, compact=True) <= current < MONITOR_END_TIME.replace(":", ""):
			market_rows = [row for row in all_rows if relative_time(MONITOR_START_TIME, 5, compact=True) <= row["tm"] <= current]
			if not market_rows or market_rows[0]["tm"] > relative_time(MONITOR_START_TIME, 65, compact=True):
				raise ValueError(f"{relative_time(MONITOR_START_TIME, 5)} 시작 수급 기록 누락")
			latest_dt = datetime.strptime(
				now.strftime("%Y%m%d") + market_rows[-1]["tm"], "%Y%m%d%H%M%S",
			)
			age = (now - latest_dt).total_seconds()
			if not 0 <= age <= 180:
				raise ValueError(f"과거 수급 최신성 부족: {age:.0f}초")
		# 장 마감 보관용 신규 조회는 실시간 원본 파일을 건드리지 않는다.
		if not persist_live:
			return all_rows
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
		history_alert_once(f"★HISTORY_INVALID_{type(exc).__name__}")
		print(f"[과거 수급 조회 실패] 기존 파일 유지: {exc}")
		return None

async def main():
    token = None
    websocket = None

    # ETF 장중 신호 및 주문은 별도 모듈이 관리한다.
    etf_live = EtfLiveScheduler()

    last_date = date.today()
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
            if now.date() != last_date:
                last_date = now.date()
                token = None
                last_etf_history_attempt = 0.0
                etf_live.reset_day()
                
                for key in executed:
                    executed[key] = False

                last_account_retry = {
                    "token": 0.0,
                    "search": 0.0,
                }

                if now.weekday() < 5:
                    log(f"DAY_{now:%m%d}")

            # 주말에는 인증, 주문, 조회 및 날짜별 저장을 모두 중단한다.
            if now.weekday() >= 5:
                if websocket is not None:
                    await websocket.stop()
                    websocket = None
                await asyncio.sleep(30)
                continue

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
                and MONITOR_START_TIME <= current < MONITOR_END_TIME
                and not executed["history_test"]
                and time.monotonic() - last_etf_history_attempt
                    >= ETF_HISTORY_RETRY_INTERVAL
            ):
                last_etf_history_attempt = time.monotonic()
                history_rows = await asyncio.to_thread(
                    check_program_history, token, "005930",
                )

                if history_rows:
                    # 08:59:55부터 08:30 이후의 당일 기록으로 기준점을 복원한다.
                    # 장 시작 전에는 09:00 이후 기록이 아직 없어도 정상이다.
                    available_rows = [
                        row for row in history_rows
                        if KRX_TAKE_PROFIT_TIME.replace(":", "") <= row["tm"] <= current.replace(":", "")
                    ]
                    if available_rows:
                        first_time = available_rows[0]["tm"]
                        latest_time = available_rows[-1]["tm"]
                        latest_dt = datetime.strptime(
                            now.strftime("%Y%m%d") + latest_time,
                            "%Y%m%d%H%M%S",
                        )
                        age = (now - latest_dt).total_seconds()
                        if first_time <= MONITOR_START_TIME.replace(":", "") and 0 <= age <= 180:
                            executed["history_test"] = True
                            print("ETF 과거 수급 최신성 검사 통과")
                            etf_live.initialize(history_rows, now)
                        else:
                            history_alert_once("★ETF_HISTORY_STALE_OR_INCOMPLETE")
                            print(f"[ETF 과거 수급 미완료] 최초={first_time}, 최신={latest_time}, 지연={age:.0f}초")
                    else:
                        history_alert_once("★ETF_HISTORY_NO_MARKET_ROWS")

            # ETF 감시 준비는 MONITOR_START_TIME부터, 실제 주문은 09:00 이후.
            # 미체결 대기/호가 고정/주도주 우선 로직은 그대로 유지한다.
            if token and executed["history_test"] and relative_time(MONITOR_START_TIME, 5) <= current < MONITOR_END_TIME:
                await etf_live.tick(token, websocket, now)

            # 15:20 이후 ETF 지정가 주문 정리 및 시장가 청산
            if token and MONITOR_END_TIME <= current < CANCEL_TAKE_PROFIT_TIME:
                await etf_live.close(token, websocket)

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
                                summary=summary,
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
                                summary=summary,
                            )

                            # 주도주 검색과 별도로 시장 필터를 갱신한다.
                            # 실패해도 후보 검색/알림은 유지하고 신규 매수만 차단한다.
                            if LEAD_KOSPI_MA20_ENABLED:
                                await asyncio.to_thread(refresh_kospi_ma20_gate, token, now.date())

                            state = load_state()

                            if summary.get("has_holding"):
                                log("SKIP_SEARCH_HOLDING")

                            else:
                                codes = await websocket.search_condition()
                                ma20_pass = (not LEAD_KOSPI_MA20_ENABLED or read_kospi_ma20_gate(now.date()))
                                candidate, candidate_codes = get_buy_code(
                                    token, codes, return_details=True, notify=ma20_pass,
                                )
                                try:
                                    save_candidate_history(
                                        now.date(), candidate_codes, candidate,
                                        ma20_pass, LEAD_KOSPI_MA20_ENABLED,
                                    )
                                except Exception as exc:
                                    print(f"[LEAD HISTORY] 저장 실패: {exc}")

                                state = load_state()

                                if candidate is None:
                                    state["candidate_code"] = None
                                    state["candidate_name"] = None
                                    save_state(state)
                                    if ma20_pass:
                                        log("No_B")

                                else:
                                    state["candidate_code"] = candidate
                                    state["candidate_name"] = None
                                    save_state(state)

                                    await websocket.register_price(candidate)
                                    if ma20_pass:
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
                MONITOR_START_TIME <= current < relative_time(MONITOR_START_TIME, 15)
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
                BUY_TIME <= current < relative_time(MONITOR_START_TIME, 15)
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

                    elif not LEAD_TRADING_ENABLED:
                        log("SKIP_LEAD_DISABLED")

                    elif LEAD_KOSPI_MA20_ENABLED and not read_kospi_ma20_gate(now.date()):
                        # 필터 미확인/조회 실패/20일선 이하: 신규 주문 금지
                        log("SKIP_LEAD_KOSPI_MA20")

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
                FORCE_SELL_TIME <= current < relative_time(FORCE_SELL_TIME, 60)
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
                BUY_CHECK_TIME <= current < relative_time(BUY_CHECK_TIME, 60)
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
                CANCEL_TAKE_PROFIT_TIME <= current < relative_time(CANCEL_TAKE_PROFIT_TIME, 60)
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

                # 장 마감 수급 이력: 계좌조회/주문 처리와 독립적으로 실패를 격리한다.
                # 기존 조회 함수의 전체 페이지/금액 검증을 통과한 행만 날짜별로 보관한다.
                try:
                    if token is None:
                        token = await asyncio.to_thread(get_token)
                    if not token:
                        raise ValueError("수급 저장용 토큰 없음")
                    closing_rows = await asyncio.to_thread(
                        check_program_history, token, "005930", persist_live=False,
                    )
                    if not closing_rows:
                        raise ValueError("장 마감 수급 이력 조회/검증 실패")
                    archive_path, archive_count, archive_updated = await asyncio.to_thread(
                        archive_program_history, closing_rows,
                        trading_date=now.strftime("%Y%m%d"),
                    )
                    print(f"[수급 날짜별 저장] {archive_path}: {archive_count}건, "
                          f"{'갱신' if archive_updated else '기존 파일 유지'}")
                except Exception as archive_exc:
                    print(f"[수급 날짜별 저장 실패] {archive_exc}")
                    history_alert_once(f"★HISTORY_ARCHIVE_{type(archive_exc).__name__}")

                # Independent read-only market research archive after existing close processing.
                try:
                    market_token = token or await asyncio.to_thread(get_token)
                    await asyncio.to_thread(collect_today, market_token)
                except Exception as market_exc:
                    print(f"[코스피 프로그램 저장 실패] {type(market_exc).__name__}: {market_exc}")


            await asyncio.sleep(0.1)

        except Exception as e:
            log(f"★SCHEDULE_{type(e).__name__}")
            print("Schedule error:", e)
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
