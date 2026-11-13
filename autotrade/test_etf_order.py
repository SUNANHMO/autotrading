
import os
import etf_state

# 테스트 전용 상태 파일 사용
etf_state.STATE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "etf_state_order_test.json"
)

from etf_order_manager import (
    start_initial_buy,
    start_switch_sell,
    record_fill,
    confirm_sell_balance_zero,
    start_switch_buy,
    confirm_buy_balance,
)


def check(condition, message):
    if not condition:
        raise AssertionError(message)

    print(f"[통과] {message}")


try:
    etf_state.clear_state()

    print("\n===== ETF 주문 관리 테스트 시작 =====\n")

    # 1. 최초 인버스 매수 주문
    start_initial_buy("INVERSE", "TEST-BUY-001", 10)

    result = record_fill("TEST-BUY-001", 4, "FILL-001")
    check(result == "PARTIAL_FILL", "매수 부분 체결")

    # 중복 체결 이벤트
    result = record_fill("TEST-BUY-001", 4, "FILL-001")
    check(result == "DUPLICATE_FILL", "중복 체결 방지")

    result = record_fill("TEST-BUY-001", 6, "FILL-002")
    check(result == "BUY_FILLED_WAIT_BALANCE", "매수 전량 체결")

    result = confirm_buy_balance(10)
    check(result is True, "인버스 잔고 확인 및 보유 확정")

    # 2. KODEX200으로 전환하기 위한 인버스 매도
    start_switch_sell("KODEX200", "TEST-SELL-001", 10)

    result = record_fill("TEST-SELL-001", 6, "FILL-003")
    check(result == "PARTIAL_FILL", "인버스 매도 부분 체결")

    # 잔량이 남아 있으면 매도 완료 처리 불가
    result = confirm_sell_balance_zero(4)
    check(result is None, "매도 잔량이 남으면 전환 차단")

    # 남은 4주 체결
    result = record_fill("TEST-SELL-001", 4, "FILL-004")
    check(result == "SELL_FILLED_WAIT_BALANCE", "인버스 매도 전량 체결")

    # 전량 체결이어도 잔고가 남으면 전환 불가
    result = confirm_sell_balance_zero(1)
    check(result is None, "잔고가 남으면 반대 ETF 매수 차단")

    # 잔고 0 확인
    result = confirm_sell_balance_zero(0)
    check(result == "KODEX200", "잔고 0 확인 후 전환 허용")

    # 3. 반대 ETF 매수
    start_switch_buy("TEST-BUY-002", 8)

    result = record_fill("TEST-BUY-002", 8, "FILL-005")
    check(result == "BUY_FILLED_WAIT_BALANCE", "KODEX200 매수 전량 체결")

    result = confirm_buy_balance(8)
    check(result is True, "KODEX200 잔고 확인 및 보유 확정")

    # 최종 상태 확인
    state = etf_state.load_state()

    check(state["position"] == "KODEX200", "최종 보유 ETF 확인")
    check(state["qty"] == 8, "최종 보유 수량 확인")
    check(state["switching"] is False, "전환 상태 종료")
    check(state["order_no"] is None, "미완료 주문 없음")

    print("\n===== 모든 주문 관리 테스트 통과 =====")

finally:
    if os.path.exists(etf_state.STATE_FILE):
        os.remove(etf_state.STATE_FILE)
