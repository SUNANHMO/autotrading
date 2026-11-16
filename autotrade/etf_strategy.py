"""삼성전자 프로그램 수급 변화폭 200억 원 기반 ETF 가상 전략."""
from a_config import REVERSE_AMOUNT
from etf_state import load_state, save_state


def update_virtual_position(net_amount, *, trading_date=None):
    """체결·미체결과 독립적으로 매 수급값마다 가상 방향을 갱신한다."""
    state = load_state()
    if trading_date and state.get("date") != trading_date:
        state.update({"date": trading_date, "virtual_position": "NONE",
                      "virtual_high": None, "virtual_low": None, "last_flow_time": None})
    net = int(net_amount)
    position = state.get("virtual_position", "NONE")
    high, low = state.get("virtual_high"), state.get("virtual_low")
    if high is None or low is None:
        high = low = net
    target = position
    if position == "NONE":
        high, low = max(high, net), min(low, net)
        if high - net >= REVERSE_AMOUNT:
            target = "INVERSE"
        elif net - low >= REVERSE_AMOUNT:
            target = "KODEX200"
    elif position == "KODEX200":
        high = max(high, net)
        if high - net >= REVERSE_AMOUNT:
            target = "INVERSE"
    elif position == "INVERSE":
        low = min(low, net)
        if net - low >= REVERSE_AMOUNT:
            target = "KODEX200"
    else:
        raise ValueError("알 수 없는 가상 포지션")
    if target != position:
        high = low = net
    state.update(virtual_position=target, virtual_high=high, virtual_low=low,
                 current_net_amount=net)
    save_state(state)
    return target


def replay_virtual_history(rows, *, trading_date, cutoff_time):
    """당일 첫 수급값부터 현재까지 시간순 재생하고 마지막 상태만 저장한다."""
    from c2_program import parse_amount
    from a_config import REVERSE_AMOUNT
    selected = sorted(
        (row for row in rows if str(row.get("tm", "")) <= cutoff_time),
        key=lambda row: str(row["tm"]),
    )
    if not selected:
        raise ValueError("재생할 당일 프로그램 수급 기록 없음")
    position, high, low = "NONE", None, None
    last_time, last_net = None, None
    for row in selected:
        net = parse_amount(str(row["prm_netprps_amt"]))
        buy = parse_amount(str(row["prm_buy_amt"]))
        sell = parse_amount(str(row["prm_sell_amt"]))
        if net != buy - sell:
            raise ValueError(f"{row['tm']} 순매수 금액 불일치")
        if high is None:
            high = low = net
        elif position == "NONE":
            high, low = max(high, net), min(low, net)
            if high - net >= REVERSE_AMOUNT:
                position = "INVERSE"
                high = low = net
            elif net - low >= REVERSE_AMOUNT:
                position = "KODEX200"
                high = low = net
        elif position == "KODEX200":
            high = max(high, net)
            if high - net >= REVERSE_AMOUNT:
                position = "INVERSE"
                high = low = net
        else:
            low = min(low, net)
            if net - low >= REVERSE_AMOUNT:
                position = "KODEX200"
                high = low = net
        last_time, last_net = str(row["tm"]), net
    state = load_state()
    state.update(date=trading_date, virtual_position=position,
                 virtual_high=high, virtual_low=low,
                 last_flow_time=last_time, current_net_amount=last_net)
    save_state(state)
    return position, len(selected), last_time, last_net
