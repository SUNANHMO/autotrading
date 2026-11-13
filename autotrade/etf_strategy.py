from a_config import REVERSE_AMOUNT
from etf_state import load_state, save_state

# ETF 코드
KODEX200 = "069500"
INVERSE = "114800"

def check_signal(net_amount):
	state = load_state()
	position = state["position"]

	# 주문 진행 여부와 관계없이 현재 수급값은 갱신
	state["current_net_amount"] = net_amount

	# 보유 방향의 당일 고점·저점은 계속 추적
	if position == "INVERSE":
		if net_amount < state["low_net_amount"]:
			state["low_net_amount"] = net_amount

	elif position == "KODEX200":
		if net_amount > state["high_net_amount"]:
			state["high_net_amount"] = net_amount

	# 주문 진행 중이거나 전환 중이면 신규 신호만 보류
	if (
		state["order_no"]
		or state["switching"]
		or state["closing_started"]
	):
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
		if net_amount >= (
			state["low_net_amount"] + REVERSE_AMOUNT
		):
			print("[ETF 전환 신호] INVERSE → KODEX200")
			save_state(state)
			return "SWITCH_TO_KODEX200"

	elif position == "KODEX200":
		if net_amount <= (
			state["high_net_amount"] - REVERSE_AMOUNT
		):
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
