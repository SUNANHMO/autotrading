
import os
import etf_state

# 실제 ETF 상태 파일을 건드리지 않도록 테스트 전용 파일 사용
etf_state.STATE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "etf_state_test.json"
)

from etf_strategy import check_signal, confirm_position


def test_step(net_amount, expected, description):
    result = check_signal(net_amount)

    print(
        f"{description} | 수급: {net_amount:,} | "
        f"예상: {expected} | 결과: {result}"
    )

    assert result == expected, (
        f"테스트 실패: 예상 {expected}, 실제 {result}"
    )


try:
    # 테스트 시작
    etf_state.clear_state()

    print("\n===== ETF 전략 가상 테스트 =====\n")

    # 1. 최초 -20,000 도달: 인버스 매수
    test_step(-20_000, "BUY_INVERSE", "최초 인버스 진입")
    confirm_position("INVERSE", -20_000, 100)

    # 2. 인버스 보유 중 하락: 최저점 갱신
    test_step(-100_000, None, "인버스 보유 중 최저점")

    # 3. 최저점에서 20,000 반등: KODEX200 전환
    test_step(-80_000, "SWITCH_TO_KODEX200", "KODEX200 전환")
    confirm_position("KODEX200", -80_000, 100)

    # 4. KODEX200 보유 중 상승: 최고점 갱신
    test_step(-60_000, None, "KODEX200 보유 중 상승")
    test_step(-50_000, None, "KODEX200 최고점 갱신")

    # 5. 최고점에서 20,000 하락: 인버스 전환
    test_step(-70_000, "SWITCH_TO_INVERSE", "인버스 재전환")
    confirm_position("INVERSE", -70_000, 100)

    print("\n===== 모든 테스트 통과 =====")

finally:
    # 테스트 전용 상태 파일 삭제
    if os.path.exists(etf_state.STATE_FILE):
        os.remove(etf_state.STATE_FILE)
