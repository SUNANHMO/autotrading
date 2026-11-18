"""ETF 20% directional-change signal, based on intraday running range.

Only uses highs/lows observed through the current tick. Initial position is
selected from the first non-zero net amount. Existing order safety gates remain.
"""
from etf_state import load_state, save_state
from etf_dc20 import update

KODEX200 = "069500"
INVERSE = "114800"
REVERSAL_FRACTION = 0.20


def check_signal(net_amount, daily_high=None, daily_low=None):
    state = load_state()
    net = int(net_amount)
    state['current_net_amount'] = net

    # A running intraday range is independent of the held ETF. Never reset on fill.
    high = max(net, int(daily_high)) if daily_high is not None else net
    low = min(net, int(daily_low)) if daily_low is not None else net
    if state.get('dc_range_initialized'):
        high = max(high, int(state['dc_daily_high']))
        low = min(low, int(state['dc_daily_low']))
    state['dc_daily_high'] = high
    state['dc_daily_low'] = low
    state['dc_range_initialized'] = True

    # While a switch/order is in progress, update observed range but do not signal.
    if state.get('order_no') or state.get('switching') or state.get('closing_started'):
        save_state(state)
        return None

    position = state['position']
    target, leg_high, leg_low = update(
        position, net, high, low,
        state.get('high_net_amount') if position != 'NONE' else None,
        state.get('low_net_amount') if position != 'NONE' else None)
    state['high_net_amount'] = leg_high
    state['low_net_amount'] = leg_low
    signal = ({'KODEX200': 'BUY_KODEX200', 'INVERSE': 'BUY_INVERSE'} if position == 'NONE'
              else {'KODEX200': 'SWITCH_TO_KODEX200', 'INVERSE': 'SWITCH_TO_INVERSE'}).get(target)
    save_state(state)
    if signal:
        print('[ETF DC20 신호]', signal, 'net=', net, 'range=', (low, high))
    return signal


def confirm_position(position, net_amount, qty):
    """Only call after verified fill; preserve intraday running range."""
    if position not in ('NONE', 'INVERSE', 'KODEX200'):
        raise ValueError('잘못된 ETF 보유 상태')
    state = load_state()
    state['position'] = position
    state['qty'] = qty
    state['high_net_amount'] = net_amount
    state['low_net_amount'] = net_amount
    save_state(state)
    print(f'[ETF 상태 변경] 보유={position}, 수급 기준={net_amount}, 수량={qty}')
