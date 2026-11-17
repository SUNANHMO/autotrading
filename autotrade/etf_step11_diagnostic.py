"""11단계: 기존 복구 검사 결과를 8~10단계 판정기로 연결하는 읽기 전용 어댑터.

실제 체결 시각의 검증된 출처가 없으므로 기준점 승인/주문 허가는 하지 않는다.
"""
import json
from etf_state import STATE_FILE
from etf_integration import evaluate_etf_integration


def diagnose_etf_recovery(recovery_result):
    """검증 결과만 이용한다. API·주문·상태 파일 쓰기는 하지 않는다."""
    if not isinstance(recovery_result, dict):
        raise ValueError("복구 결과 형식 오류")
    replay = recovery_result.get("replay")
    if not isinstance(replay, dict):
        raise ValueError("수급 가상 재생 결과 없음")
    with open(STATE_FILE, encoding="utf-8") as handle:
        saved = json.load(handle)
    if not isinstance(saved, dict):
        raise ValueError("저장 ETF 상태 형식 오류")
    raw_qty = saved.get("qty")
    if isinstance(raw_qty, bool) or raw_qty is None:
        raise ValueError("저장 ETF 수량 누락")
    qty_text = str(raw_qty).replace(",", "").strip()
    if not qty_text.isdigit():
        raise ValueError("저장 ETF 수량 형식 오류")
    saved_qty = int(qty_text)
    count = recovery_result.get("unfilled_count")
    details = recovery_result.get("unfilled_details")
    if not isinstance(details, list) or type(count) is not int or count != len(details):
        raise ValueError("미체결 상세의 완전성 미확인")
    pending = any(bool(saved.get(k)) for k in (
        "order_no", "order_type", "switching", "target_position",
        "closing_started", "closing_order_no"))
    pending |= any(saved.get(k) not in (0, "0", None) for k in (
        "order_qty", "filled_qty", "remaining_qty"))
    result = evaluate_etf_integration(
        strategy_position=replay.get("position"),
        account_position=recovery_result.get("account_position"),
        account_qty=recovery_result.get("account_qty"),
        saved_position=saved.get("position"), saved_qty=saved_qty,
        unfilled_count=count,
        # 기존 복구 검사 결과에는 타종목/주도주 차단 여부가 없으므로 보수적으로 차단.
        lead_blocked=True, pending_state=pending,
        account_verified=(recovery_result.get("account_position") is not None
                          and recovery_result.get("account_qty") is not None),
        orders_verified=True,
        fill_time=None, fill_verified=False,
        history_rows=None, history_verified=False,
    )
    result["can_submit_order"] = False
    return result
