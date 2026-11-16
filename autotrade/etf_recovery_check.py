"""ETF 장중 복구의 읽기 전용 계좌 대조 (5단계).

복구 승인 판정만 수행하며 주문·상태 파일 변경은 하지 않는다.
5단계에서는 h_schedule.py에 연결하지 않는다.
"""
import json
import os
from datetime import datetime

from c2_program import get_etf_unfilled_orders
from d_account import get_account, _normalize_code
from etf_recovery import replay_program_history
from etf_state import STATE_FILE

ETF_CODES = {"069500": "KODEX200", "114800": "INVERSE"}


def _strict_qty(value):
    if isinstance(value, bool) or value is None:
        raise ValueError("보유수량 누락")
    text = str(value).replace(",", "").strip()
    if not text or not text.lstrip("+").isdigit():
        raise ValueError(f"보유수량 형식 오류: {value!r}")
    result = int(text)
    if result < 0:
        raise ValueError("보유수량 음수")
    return result


def _read_saved_state():
    # etf_state.load_state()는 파일 누락 시 새 파일을 생성하므로 사용하지 않는다.
    with open(STATE_FILE, encoding="utf-8") as handle:
        state = json.load(handle)
    if not isinstance(state, dict):
        raise ValueError("ETF 상태 파일 형식 오류")
    return state


def check_etf_recovery(token, now=None, history_file=None):
    """읽기 전용 검증 결과 반환. 모든 불확실성은 approved=False."""
    result = {"approved": False, "reason": None, "replay": None,
              "account_position": None, "account_qty": None,
              "unfilled_count": None}
    try:
        if not token:
            raise ValueError("인증 토큰 없음")
        now = now or datetime.now()
        replay = replay_program_history(history_file=history_file, now=now)
        if not isinstance(replay, dict) or replay.get("position") not in ("NONE", "KODEX200", "INVERSE"):
            raise ValueError("가상 재생 결과 형식 오류")
        result["replay"] = replay

        account = get_account(token)
        if not isinstance(account, dict) or not isinstance(account.get("stk_acnt_evlt_prst"), list):
            raise ValueError("계좌 보유종목 응답 누락 또는 조회 실패")
        holdings = account["stk_acnt_evlt_prst"]
        etf_qty = {code: 0 for code in ETF_CODES}
        lead_holdings = []
        for row in holdings:
            if not isinstance(row, dict):
                raise ValueError("계좌 보유종목 행 형식 오류")
            code = _normalize_code(row.get("stk_cd"))
            qty = _strict_qty(row.get("rmnd_qty"))
            if qty == 0:
                continue
            if not code:
                raise ValueError("보유 종목코드 누락")
            if code in ETF_CODES:
                etf_qty[code] += qty
            else:
                lead_holdings.append(code)

        active = [code for code, qty in etf_qty.items() if qty > 0]
        if len(active) > 1:
            raise ValueError("ETF 두 종목 동시 보유")
        account_position = ETF_CODES[active[0]] if active else "NONE"
        result["account_position"] = account_position
        result["account_qty"] = etf_qty[active[0]] if active else 0

        unfilled = get_etf_unfilled_orders(token)
        if unfilled is None or not isinstance(unfilled, list):
            raise ValueError("ETF 미체결 조회 실패")
        result["unfilled_count"] = len(unfilled)
        if unfilled:
            raise ValueError("ETF 미체결 주문 존재")
        if lead_holdings:
            raise ValueError("주도주 또는 다른 종목 보유 중")

        state = _read_saved_state()
        if state.get("position") not in ("NONE", "KODEX200", "INVERSE"):
            raise ValueError("저장된 ETF 포지션 오류")
        if state["position"] != account_position:
            raise ValueError("저장된 ETF 포지션과 실제 잔고 불일치")
        if _strict_qty(state.get("qty")) != result["account_qty"]:
            raise ValueError("저장된 ETF 수량과 실제 잔고 불일치")
        if any(state.get(field) for field in (
            "order_no", "order_type", "switching", "target_position",
            "closing_started", "closing_order_no",
        )):
            raise ValueError("저장된 ETF 주문·전환·청산 진행 상태 존재")
        for field in ("order_qty", "filled_qty", "remaining_qty"):
            if _strict_qty(state.get(field)) != 0:
                raise ValueError(f"저장된 ETF 주문 수량 잔존: {field}")
        if replay["position"] != account_position:
            raise ValueError("가상 재생 포지션과 실제 잔고 불일치")
        if account_position != "NONE":
            # 수급 최고·최저점은 체결 시각과 연결돼야 하므로 이 단계에서 자동 승인하지 않는다.
            raise ValueError("보유 ETF의 실제 체결 시점·전환 기준점 미검증")

        result["approved"] = True
        result["reason"] = "가상 미보유·실제 미보유·미체결 없음·저장 상태 일치"
    except Exception as exc:
        result["reason"] = f"{type(exc).__name__}: {exc}"
    return result
