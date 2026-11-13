from a_config import REVERSE_AMOUNT
from etf_state import load_state, save_state

# ETF 코드
KODEX200 = "069500"
INVERSE = "114800"


def check_signal(
	net_amount,
	daily_high=None,
	daily_low=None,
):
	state = load_state()
	position = state["position"]

	net_amount = int(net_amount)

	state["current_net_amount"] = net_amount

	# 당일 실시간 최고·최저 수급을 반영한다.
	if position == "INVERSE":
		if daily_low is not None:
			state["low_net_amount"] = min(
				int(state.get("low_net_amount") or daily_low),
				int(daily_low),
			)

		state["low_net_amount"] = min(
			int(state.get("low_net_amount") or net_amount),
			net_amount,
		)

	elif position == "KODEX200":
		if daily_high is not None:
			state["high_net_amount"] = max(
				int(state.get("high_net_amount") or daily_high),
				int(daily_high),
			)

		state["high_net_amount"] = max(
			int(state.get("high_net_amount") or net_amount),
			net_amount,
		)

	# 미체결 주문이나 전환·마감 진행 중에는 신호만 갱신하지 않는다.
	if (
		state.get("order_no")
		or state.get("switching")
		or state.get("closing_started")
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
