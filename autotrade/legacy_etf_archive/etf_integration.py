"""10단계: ETF 복구 판정(8단계)과 체결 기준점(9단계)의 읽기 전용 통합.

주문·API·파일 I/O 없음. 검증된 스냅샷을 받아 다음 *진단 작업*만 반환한다.
절대로 주문 승인 신호로 사용하지 않는다.
"""
from etf_reconcile_plan import plan_etf_reconciliation
from etf_fill_anchor import recover_etf_fill_anchor


def evaluate_etf_integration(*, strategy_position, account_position, account_qty,
                             saved_position, saved_qty, unfilled_count,
                             lead_blocked, pending_state=False,
                             account_verified=False, orders_verified=False,
                             fill_time=None, fill_verified=False,
                             history_rows=None, history_verified=False,
                             now_time=None):
    """실제 잔고/주문 불확실성을 우선 차단하고, 필요할 때만 기준점을 계산한다."""
    result = {
        "status": "BLOCKED", "next_check": "VERIFY_INPUTS", "reason": "",
        "reconciliation": None, "anchor": None, "can_submit_order": False,
    }
    if type(fill_verified) is not bool or type(history_verified) is not bool:
        result["reason"] = "체결/수급 검증 플래그 형식 오류"
        return result
    anchor_verified = bool(fill_verified and history_verified and fill_time
                           and isinstance(history_rows, list))
    plan = plan_etf_reconciliation(
        strategy_position=strategy_position,
        account_position=account_position, account_qty=account_qty,
        saved_position=saved_position, saved_qty=saved_qty,
        unfilled_count=unfilled_count, lead_blocked=lead_blocked,
        pending_state=pending_state, anchor_verified=anchor_verified,
        account_verified=account_verified, orders_verified=orders_verified,
    )
    result["reconciliation"] = plan
    result["next_check"] = plan["next_check"]
    result["reason"] = plan["reason"]
    if plan["alignment"] in ("UNKNOWN", "STATE_MISMATCH", "ORDER_PENDING", "LEAD_PRIORITY", "ANCHOR_UNKNOWN"):
        return result
    if account_position == "NONE":
        result.update(status="OBSERVE_ONLY", next_check="EVALUATE_INITIAL_SIGNAL",
                      reason="미보유 상태: 신규 주문 허가는 별도 통합 검증 필요")
        return result
    if not anchor_verified:
        result.update(next_check="VERIFY_FILL_ANCHOR", reason="체결 기준점 검증 필요")
        return result
    try:
        anchor = recover_etf_fill_anchor(
            position=account_position, fill_time=fill_time,
            rows=history_rows, fill_verified=fill_verified,
            history_verified=history_verified, now_time=now_time,
        )
    except (ValueError, TypeError, KeyError) as exc:
        result.update(next_check="VERIFY_FILL_ANCHOR", reason=f"기준점 복구 실패: {exc}")
        return result
    result["anchor"] = anchor
    if anchor["switch_signal"]:
        result.update(status="SWITCH_SIGNAL_OBSERVED", next_check="VERIFY_SWITCH_PRECONDITIONS",
                      reason="실제 체결 이후 전환 조건 관측: 주문 실행은 여전히 차단")
    else:
        result.update(status="MONITORING", next_check="CONTINUE_MONITORING",
                      reason="실제 체결 기준으로 전환 조건 미충족")
    return result
