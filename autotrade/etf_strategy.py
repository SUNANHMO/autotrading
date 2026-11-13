from a_config import REVERSE_AMOUNT
from etf_state import load_state, save_state

# ETF 코드
KODEX200 = "069500"
INVERSE = "114800"


def check_signal(net_amount, daily_high=None, daily_low=None):
	state = load_state()
	position = state["position"]

	state["current_net_amount"] = net_amount

	if position == "INVERSE":
		observed_low = net_amount if daily_low is None else daily_low
		state["low_net_amount"] = min(
			state["low_net_amount"], observed_low
		)

	elif position == "KODEX200":
		observed_high = net_amount if daily_high is None else daily_high
		state["high_net_amount"] = max(
			state["high_net_amount"], observed_high
		)

	if state["order_no"] or state["switching"] or state["closing_started"]:
		save_state(state)
		return None

	if position == "NONE":
		if net_amount >= REVERSE_AMOUNT:
			signal = "BUY_KODEX200"
		elif net_amount <= -REVERSE_AMOUNT:
			signal = "BUY_INVERSE"
		else:
			signal = None

		if signal:
			print("[ETF 신호]", signal, net_amount)

		save_state(state)
		return signal

	if position == "INVERSE":
		if net_amount >= state["low_net_amount"] + REVERSE_AMOUNT:
			print("[ETF 전환 신호] INVERSE → KODEX200")
			save_state(state)
			return "SWITCH_TO_KODEX200"

	elif position == "KODEX200":
		if net_amount <= state["high_net_amount"] - REVERSE_AMOUNT:
			print("[ETF 전환 신호] KODEX200 → INVERSE")
			save_state(state)
			return "SWITCH_TO_INVERSE"

	save_state(state)
	return None


def confirm_position(position, net_amount, qty):
	"""
	실제 주문 체결 및 잔고 확인 후 호출할 함수.
	주문 접수만으로 호출하면 안 됨.
	"""
	if position not in ("NONE", "INVERSE", "KODEX200"):
		raise ValueError("잘못된 ETF 보유 상태")
	state = load_state()
	state["position"] = position
	state["qty"] = qty
	# 실제 전환 완료 시 새로운 추적 기준 설정
	state["high_net_amount"] = net_amount
	state["low_net_amount"] = net_amount
	save_state(state)
	print(
		f"[ETF 상태 변경] 보유={position}, "
		f"수급 기준={net_amount}, 수량={qty}")
