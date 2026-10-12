
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "state.json")

def default_state():
	return {
		# 실제 보유 상태
		"holding": False,
		"code": None,
		"name": None,
		"qty": 0,
		"buy_price": 0,
		"buy_date": None,

		# 매수 후보 및 신규 매수 주문
		"candidate_code": None,
		"candidate_name": None,
		"buy_order_no": None,
		"buy_order_qty": 0,
		"buy_filled_qty": 0,
		"buy_remaining_qty": 0,
		"buy_fill_amount": 0,

		# 신규 매수분인지, 기존 보유분인지 구분
		"position_origin": None,

		# 익절·손절 주문 관리
		"take_profit_order_no": None,
		"profit_market": None,
		"sell_order_no": None,
		"stop_loss_triggered": False,

		# 미체결 매수 취소 조건 확인용
		"opening_price": 0,
		"opening_high_cancelled": False,}

def save_state(state):
	with open(STATE_FILE, "w", encoding="utf-8") as f:
		json.dump(state, f, ensure_ascii=False, indent=4)

def load_state():
	if not os.path.exists(STATE_FILE):
		state = default_state()
		save_state(state)
		return state

	with open(STATE_FILE, "r", encoding="utf-8") as f:
		state = json.load(f)

	# 기존 state.json에 새 필드가 없을 경우 기본값 추가
	defaults = default_state()
	for key, value in defaults.items():
		state.setdefault(key, value)

	return state

def clear_state():
	state = default_state()
	save_state(state)
	return state
