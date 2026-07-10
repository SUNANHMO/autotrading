import json
import os
from telegram_log import log

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "state.json")

def default_state():
	return {
		"holding": False,
		"code": None,
		"name": None,
		"qty": 0,
		"buy_price": 0,
		"buy_date": None,
		"holding_days": 0,
		"buy_order_no": None,		   # 15:29:59 동시호가 매수 체결 조회용
		"take_profit_order_no": None,  # 익절 주문 번호
		"profit_market" : None,        # 익절 주문 시장
		"sell_order_no": None}		   # 시장가 매도 주문번호

def save_state(state):
	with open(STATE_FILE, "w", encoding="utf-8") as f:
		json.dump(state, f, ensure_ascii=False, indent=4)

def load_state():
	if not os.path.exists(STATE_FILE):
		state = default_state()
		save_state(state)
		return state

	with open(STATE_FILE, "r", encoding="utf-8") as f:
		return json.load(f)

def clear_state():
    state = default_state()
    save_state(state)
    return state