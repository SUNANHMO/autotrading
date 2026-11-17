"""8단계: ETF 전략 목표와 실제 계좌 상태를 분리하는 순수 판정기.

외부 API, 주문, 파일 읽기/쓰기 없음. 결과는 진단/테스트용이며 주문 실행 허가가 아니다.
"""

POSITIONS = frozenset(("NONE", "KODEX200", "INVERSE"))


def plan_etf_reconciliation(*, strategy_position, account_position,
                            account_qty, unfilled_count, lead_blocked,
                            saved_position, saved_qty, pending_state=False,
                            anchor_verified=False, account_verified=False,
                            orders_verified=False):
    """검증된 스냅샷만 사용해 차이와 다음 *검증 작업*을 설명한다.

    strategy_position: 당일 수급 가상 재생 결과(실제 체결 이력 아님)
    account_position/qty: 실계좌 잔고
    saved_position/qty: 저장된 ETF 상태
    anchor_verified: 실제 체결 이후 추적 기준점 검증 완료 여부
    """
    result = {
        "strategy_target": strategy_position,
        "account_position": account_position,
        "account_qty": account_qty,
        "saved_position": saved_position,
        "saved_qty": saved_qty,
        "alignment": "UNKNOWN",
        "next_check": "VERIFY_INPUTS",
        "reason": "",
        "can_submit_order": False,
    }

    if (strategy_position not in POSITIONS or account_position not in POSITIONS
            or saved_position not in POSITIONS):
        result["reason"] = "포지션 값 오류 또는 누락"
        return result
    if (type(account_qty) is not int or type(saved_qty) is not int
            or account_qty < 0 or saved_qty < 0
            or type(unfilled_count) is not int or unfilled_count < 0):
        result["reason"] = "수량 또는 미체결 건수 검증 실패"
        return result
    if any(type(x) is not bool for x in (
            lead_blocked, pending_state, anchor_verified,
            account_verified, orders_verified)):
        result["reason"] = "검증 플래그 형식 오류"
        return result
    if not account_verified or not orders_verified:
        result["reason"] = "계좌 또는 미체결 조회의 완전성 미확인"
        return result
    if (account_position == "NONE") != (account_qty == 0):
        result["reason"] = "실제 잔고의 종목/수량 불일치"
        return result
    if (saved_position == "NONE") != (saved_qty == 0):
        result["reason"] = "저장 상태의 종목/수량 불일치"
        return result

    if account_position != saved_position or account_qty != saved_qty:
        result.update(alignment="STATE_MISMATCH", next_check="RECONCILE_SAVED_STATE",
                      reason="실제 잔고와 저장 상태 불일치: 체결 내역 검증 필요")
        return result

    if unfilled_count or pending_state:
        result.update(alignment="ORDER_PENDING", next_check="VERIFY_EXISTING_ORDER",
                      reason="진행 중이거나 결과가 불명확한 주문 존재")
        return result

    if lead_blocked:
        result.update(alignment="LEAD_PRIORITY", next_check="WAIT_LEAD_CLEAR",
                      reason="주도주 우선순위: ETF 신규 주문 판단 보류")
        return result

    if account_position != "NONE" and not anchor_verified:
        result.update(alignment="ANCHOR_UNKNOWN", next_check="VERIFY_FILL_ANCHOR",
                      reason="실제 체결 시점의 수급 기준점 미검증")
        return result

    if strategy_position == account_position:
        result.update(alignment="MATCH", next_check="CONTINUE_MONITORING",
                      reason="가상 방향과 실제 보유 일치; 주문 허가는 별도")
    else:
        result.update(alignment="DIRECTION_DIFFERENCE", next_check="EVALUATE_FROM_REAL_ANCHOR",
                      reason="가상 방향과 실제 보유 차이; 실제 체결 이후 수급으로 전환 신호 재판정 필요")
    return result
