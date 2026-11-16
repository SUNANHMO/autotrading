"""9단계: 검증된 실제 ETF 진입 체결 시각 이후 수급 기준점 복구.

읽기 전용 순수 계산. 체결 조회/검증, 계좌 조회, 주문, 파일 변경 없음.
fill_time은 외부에서 체결내역으로 검증한 HHMMSS 값이어야 한다.
rows는 완전성·날짜·종목·단위가 검증된 당일 ka90008 데이터여야 한다.
"""
from datetime import datetime
from a_config import REVERSE_AMOUNT
from etf_recovery import parse_amount

POSITIONS = frozenset(("KODEX200", "INVERSE"))


def recover_etf_fill_anchor(*, position, fill_time, rows,
                            fill_verified=False, history_verified=False,
                            now_time=None):
    """진입 체결 시각의 수급값을 기준으로 전환 조건을 계산한다.

    반환된 switch_signal은 진단용이며 주문 허가가 아니다.
    체결 시각과 같은 초의 수급은 체결 전/후 순서를 알 수 없어 기준점으로
    사용하지 않는다. 체결 *이전* 마지막 수급을 초기 기준점으로 사용한다.
    """
    if position not in POSITIONS:
        raise ValueError("실제 보유 ETF 방향 오류")
    if type(fill_verified) is not bool or type(history_verified) is not bool:
        raise ValueError("검증 플래그 형식 오류")
    if not fill_verified or not history_verified:
        raise ValueError("체결 시각과 수급 이력 검증이 모두 필요")

    def valid_time(value, label):
        if not isinstance(value, str) or len(value) != 6 or not value.isdigit():
            raise ValueError(f"{label} HHMMSS 형식 오류")
        try:
            datetime.strptime(value, "%H%M%S")
        except ValueError as exc:
            raise ValueError(f"{label} 시간 값 오류") from exc
        return value

    fill_time = valid_time(fill_time, "체결 시각")
    if not "090000" <= fill_time < "152000":
        raise ValueError("체결 시각이 ETF 장중 진입 범위를 벗어남")
    if now_time is not None:
        now_time = valid_time(now_time, "현재 시각")
        if now_time < fill_time:
            raise ValueError("현재 시각보다 미래의 체결")
    if not isinstance(rows, list) or not rows:
        raise ValueError("수급 이력 누락")

    normalized = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("수급 행 형식 오류")
        tm = valid_time(row.get("tm"), "수급 시각")
        if tm in seen:
            raise ValueError("중복 수급 시각")
        seen.add(tm)
        try:
            net = parse_amount(row["prm_netprps_amt"])
            buy = parse_amount(row["prm_buy_amt"])
            sell = parse_amount(row["prm_sell_amt"])
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError("수급 금액 형식 오류") from exc
        if buy < 0 or sell < 0 or net != buy - sell:
            raise ValueError("수급 금액 불일치")
        if now_time is not None and tm > now_time:
            raise ValueError("현재 시각 이후 수급 기록")
        normalized.append((tm, net))
    normalized.sort()

    # 동일 초에 체결과 수급이 발생했다면 선후관계를 알 수 없으므로 제외한다.
    earlier = [(tm, net) for tm, net in normalized if "090000" <= tm < fill_time]
    if not earlier:
        raise ValueError("체결 이전 수급 기준점이 없음")
    anchor_time, anchor_net = earlier[-1]
    high = low = anchor_net
    last_time = anchor_time
    current_net = anchor_net
    switch_signal = False
    switch_time = None
    observed = 0
    for tm, net in normalized:
        if tm <= fill_time or tm > "152000":
            continue
        observed += 1
        current_net = net
        last_time = tm
        if position == "KODEX200":
            high = max(high, net)
            if not switch_signal and high - net >= REVERSE_AMOUNT:
                switch_signal = True
                switch_time = tm
                break
        else:
            low = min(low, net)
            if not switch_signal and net - low >= REVERSE_AMOUNT:
                switch_signal = True
                switch_time = tm
                break
    return {
        "position": position,
        "fill_time": fill_time,
        "anchor_time": anchor_time,
        "anchor_net_amount": anchor_net,
        "high_net_amount": high,
        "low_net_amount": low,
        "current_net_amount": current_net,
        "last_time": last_time,
        "post_fill_rows": observed,
        "switch_signal": switch_signal,
        "switch_time": switch_time,
        "can_submit_order": False,
        "note": "진단 전용: 실제 체결내역 및 수급 데이터 완전성은 호출자가 검증해야 함",
    }
