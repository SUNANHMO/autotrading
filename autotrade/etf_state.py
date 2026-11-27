
import json
import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "etf_state.json")

def default_state():
    return {
        "date": None,
        "virtual_position": "NONE",
        "first_position": "NONE",
        "execution_dc20_enabled": None,
        "virtual_high": None,
        "virtual_low": None,
        "last_flow_time": None,
        "lead_sell_completed_date": None,
        "pending_action": None,
        "signal_target": None,
        "pending_quote_target": None,
        "pending_quote_required": None,
        "signal_initial_entry": False,
        "signal_prices": {},
        "active_target": None,
        "active_sell_code": None,
        "active_sell_price": None,
        "active_buy_price": None,
        "active_stage": None,
        "active_buy_order_no": None,
        "pending_order_no": None,
        "cancel_requested": False, 
        "position": "NONE", # 보유 상태: NONE / INVERSE / KODEX200
        "qty": 0, # 현재 보유 ETF 수량
        "high_net_amount": 0, # 현재 보유 방향에서 추적하는 최고점
        "low_net_amount": 0, # 현재 보유 방향에서 추적하는 최저점
        "current_net_amount": 0, # 마지막으로 처리한 프로그램 수급값
        # 주문 상태
        "order_no": None,
        "order_type": None,
        "order_qty": 0,
        "filled_qty": 0,
        "remaining_qty": 0,
        # 전환 진행 상태
        "switching": False,
        "target_position": None,
        # 장 마감 정리 상태
        "closing_started": False,
        "closing_order_no": None,
        "processed_fill_ids": [],
        "cancel_status": None,
        "cancel_reason": None,
        "cancel_order_no": None,}

def save_state(state):
    temp_file = STATE_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=4)
    os.replace(temp_file, STATE_FILE)

def load_state():
    if not os.path.exists(STATE_FILE):
        state = default_state()
        save_state(state)
        return state
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        state = default_state()
        state.update(saved)
        return state
    except (json.JSONDecodeError, OSError):
        return default_state()

def clear_state():
    state = default_state()
    save_state(state)
    return state
