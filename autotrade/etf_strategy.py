"""삼성전자 프로그램 누적 순매수의 당일 범위 20% 기반 ETF 가상 전략."""
from a_config import REVERSE_AMOUNT
from etf_state import load_state, save_state


def _advance(position, net, daily_high, daily_low, leg_high, leg_low):
    """실시간과 과거 재생이 공유하는 전환 계산. 금액 단위: 백만원."""
    daily_high = net if daily_high is None else max(daily_high, net)
    daily_low = net if daily_low is None else min(daily_low, net)
    threshold = (daily_high - daily_low) * REVERSE_AMOUNT
    if leg_high is None or leg_low is None:
        leg_high = leg_low = net
    target = position
    if position == "NONE":
        # 초기 방향은 관측된 첫 비영(非零) 순매수 부호로 결정한다.
        if net > 0:
            target = "KODEX200"
        elif net < 0:
            target = "INVERSE"
    elif position == "KODEX200":
        leg_high = max(leg_high, net)
        if threshold > 0 and leg_high - net >= threshold:
            target = "INVERSE"
    elif position == "INVERSE":
        leg_low = min(leg_low, net)
        if threshold > 0 and net - leg_low >= threshold:
            target = "KODEX200"
    else:
        raise ValueError("알 수 없는 가상 포지션")
    if target != position:
        leg_high = leg_low = net
    return target, daily_high, daily_low, leg_high, leg_low


def update_virtual_position(net_amount, *, trading_date=None):
    """매 수급값마다 방향을 갱신하고 당일 전체/방향별 극값을 저장한다."""
    state = load_state()
    if trading_date and state.get("date") != trading_date:
        state.update(date=trading_date, virtual_position="NONE",
                     virtual_high=None, virtual_low=None,
                     dc_daily_high=None, dc_daily_low=None, last_flow_time=None)
    net = int(net_amount)
    result = _advance(state.get("virtual_position", "NONE"), net,
                      state.get("dc_daily_high"), state.get("dc_daily_low"),
                      state.get("virtual_high"), state.get("virtual_low"))
    position, day_high, day_low, high, low = result
    state.update(virtual_position=position, dc_daily_high=day_high,
                 dc_daily_low=day_low, virtual_high=high, virtual_low=low,
                 current_net_amount=net)
    save_state(state)
    return position


def replay_virtual_history(rows, *, trading_date, cutoff_time):
    """당일 첫 수급값부터 시간순 재생하고 마지막 상태만 저장한다."""
    from c2_program import parse_amount
    selected = sorted(
        (row for row in rows if str(row.get("tm", "")) <= cutoff_time),
        key=lambda row: str(row["tm"]),
    )
    if not selected:
        raise ValueError("재생할 당일 프로그램 수급 기록 없음")
    position, day_high, day_low, high, low = "NONE", None, None, None, None
    last_time, last_net = None, None
    for row in selected:
        net = parse_amount(str(row["prm_netprps_amt"]))
        buy = parse_amount(str(row["prm_buy_amt"]))
        sell = parse_amount(str(row["prm_sell_amt"]))
        if net != buy - sell:
            raise ValueError(f"{row['tm']} 순매수 금액 불일치")
        position, day_high, day_low, high, low = _advance(
            position, net, day_high, day_low, high, low)
        last_time, last_net = str(row["tm"]), net
    state = load_state()
    state.update(date=trading_date, virtual_position=position,
                 dc_daily_high=day_high, dc_daily_low=day_low,
                 virtual_high=high, virtual_low=low,
                 last_flow_time=last_time, current_net_amount=last_net)
    save_state(state)
    return position, len(selected), last_time, last_net
