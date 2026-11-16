import asyncio
import time
import requests
import json

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
from i_healthcheck import process_check


ETF_CODES = {"069500", "114800"}
# 실계좌 주문 활성화는 통합 검증 후 수동 승인
ETF_LIVE_ORDERS_ENABLED = True


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

	all_rows = []
	seen_keys = set()
	seen_keys_rows = set()
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

				# 동일 시각의 서로 다른 수급 스냅샷도 순서대로 보존한다.
				# 연속조회 페이지 경계의 완전 중복 행만 제외한다.
				key = (tm, net, buy_amt, sell_amt)
				if key in seen_keys_rows:
					duplicate_count += 1
					continue
				seen_keys_rows.add(key)
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


async def notify_etf_virtual_change(websocket, net_amount, old_position, new_position):
    """가상 방향 변경 알림만 발송한다. 실제 주문과는 독립적이다."""
    if new_position == old_position or new_position not in ("KODEX200", "INVERSE"):
        return
    from telegram_log import send_message
    def quote_price(code, field):
        quote = websocket.get_etf_quote(code, max_age_seconds=3) if websocket else None
        value = quote.get(field) if quote else None
        return f"{int(value):,}" if value and int(value) > 0 else "미수신"
    net_eok = net_amount / 100  # 키움 금액 단위: 백만원 -> 억원
    net_label = f"{net_eok:,.2f}".rstrip("0").rstrip(".") if net_eok % 1 else f"{int(net_eok):,}"
    parts = [f"(SS) PG_{net_label}"]
    if old_position == "INVERSE":
        parts.append(f"D_{quote_price('114800', 'best_ask')}")
    elif old_position == "KODEX200":
        parts.append(f"U_{quote_price('069500', 'best_ask')}")
    if new_position == "INVERSE":
        parts.append(f"D_{quote_price('114800', 'best_bid')}")
    else:
        parts.append(f"U_{quote_price('069500', 'best_bid')}")
    message = " / ".join(parts)
    print(f"[ETF 가상 방향 텔레그램] {message}")
    await asyncio.to_thread(send_message, message)


async def monitor_etf_signal(now, last_flow_signature, token, websocket):
    """실시간 가상 포지션은 주문/체결 상태와 관계없이 갱신한다."""
    if not (MONITOR_START_TIME <= now.strftime("%H:%M:%S") < "15:20:00"):
        return last_flow_signature
    flow = read_live_program_flow(now)
    if flow is None:
        return last_flow_signature
    signature = (flow["time"], flow["net_amount"])
    if signature == last_flow_signature:
        return last_flow_signature
    from etf_strategy import update_virtual_position
    from etf_state import load_state as read_etf_state, save_state as write_etf_state
    state = read_etf_state()
    if (state.get("date") == now.strftime("%Y%m%d")
            and state.get("last_flow_time")
            and flow["time"] <= state["last_flow_time"]):
        return signature
    old_position = state.get("virtual_position", "NONE")
    target = update_virtual_position(flow["net_amount"], trading_date=now.strftime("%Y%m%d"))
    if target != old_position:
        await notify_etf_virtual_change(websocket, flow["net_amount"], old_position, target)
    state = read_etf_state()
    state["last_flow_time"] = flow["time"]
    write_etf_state(state)
    print(f"[ETF 가상 방향] {flow['time']} {flow['net_amount']} -> {target}")
    return signature

def lead_has_priority(lead, etf_state, trading_date, *, search_completed):
    """주도주 검색 전/매매 중에는 ETF 진입 보류, 전량 매도 완료 시 해제."""
    if not search_completed:
        return True
    if lead.get("holding") or lead.get("buy_order_no"):
        return True
    if etf_state.get("lead_sell_completed_date") == trading_date:
        return False
    return bool(lead.get("candidate_code"))


async def main():
    token = None
    websocket = None

    # 과거 수급 복원 성공 전에는 ETF 실시간 방향 갱신 및 신규 주문 금지
    etf_recovery_completed = False

    last_date = date.today()
    last_etf_flow_signature = None
    last_etf_reconcile_at = 0.0  # ETF 계좌 정합성 확인만 최대 1초에 한 번
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
            # 장중 재시작 시에도 08:30경 당일 최초 기록부터 가상 방향을 복원한다.
            if (MONITOR_START_TIME <= current < "15:20:00" and token
                    and not etf_recovery_completed
                    and time.monotonic() - last_etf_history_attempt >= ETF_HISTORY_RETRY_INTERVAL):
                last_etf_history_attempt = time.monotonic()
                rows = await asyncio.to_thread(check_program_history, token)
                if rows:
                    try:
                        from etf_strategy import replay_virtual_history
                        position, count, flow_tm, net = replay_virtual_history(
                            rows, trading_date=now.strftime("%Y%m%d"),
                            cutoff_time=datetime.now().strftime("%H%M%S"),
                        )
                        etf_recovery_completed = True
                        last_etf_flow_signature = (flow_tm, net)
                        # 재시작 시 과거 변경을 연속 발송하지 않고 현재 방향만 한 번 알림
                        if position != "NONE":
                            await notify_etf_virtual_change(websocket, net, "NONE", position)
                        print(f"[ETF 과거 복원 완료] {count}건 / 마지막 {flow_tm} "
                              f"/ 순매수 {net} / 가상 포지션 {position}")
                    except (ValueError, KeyError, TypeError) as exc:
                        print(f"[ETF 과거 복원 실패] {exc}")
            if etf_recovery_completed:
                last_etf_flow_signature = await monitor_etf_signal(
                    now, last_etf_flow_signature, token, websocket,
                )
            if (ETF_LIVE_ORDERS_ENABLED and token
                    and time.monotonic() - last_etf_reconcile_at >= 1.0):
                last_etf_reconcile_at = time.monotonic()
                from etf_execution import reconcile_etf
                virtual_target = load_etf_state().get("virtual_position", "NONE")
                lead = load_state()
                lead_priority = lead_has_priority(
                    lead, load_etf_state(), now.strftime("%Y%m%d"),
                    search_completed=(executed["search"] or current >= "09:00:10"),
                )
                if current >= "09:00:10" and not lead.get("holding") and not lead.get("buy_order_no"):
                    lead_priority = False
                if (etf_recovery_completed and MONITOR_START_TIME <= current < "15:20:00"):
                    await asyncio.to_thread(reconcile_etf, token, websocket, virtual_target,
                                            lead_priority=lead_priority)
                elif "15:20:00" <= current < "15:30:00":
                    await asyncio.to_thread(reconcile_etf, token, websocket, virtual_target,
                                            closing=True)
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
