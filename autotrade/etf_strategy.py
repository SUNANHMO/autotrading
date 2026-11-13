from a_config import REVERSE_AMOUNT
from etf_state import load_state, save_state

# ETF 코드
KODEX200 = "069500"
INVERSE = "114800"

def check_signal(net_amount):
	"""
	삼성전자 프로그램 순매수 금액으로 ETF 전환 신호 판단
	net_amount 단위: 백만 원
	최초:
		+20,000 도달 -> KODEX200 매수
		-20,000 도달 -> 인버스 매수
	인버스 보유:
		최저점에서 20,000 상승 -> KODEX200 전환
	KODEX200 보유:
		최고점에서 20,000 하락 -> 인버스 전환
	"""
	state = load_state()
	position = state["position"]
    
    # 주문 또는 ETF 전환이 진행 중이면 새 신호를 무시
	if state["order_no"] or state["switching"]:
		return None
	
    # 현재 수급값 저장
	state["current_net_amount"] = net_amount

	# 최초 진입
	if position == "NONE":
		if net_amount >= REVERSE_AMOUNT:
			signal = "BUY_KODEX200"
		elif net_amount <= -REVERSE_AMOUNT:
			signal = "BUY_INVERSE"
		else:
			signal = None
		if signal:
			print(f"[ETF 신호] 최초 진입: {signal}, 수급={net_amount}")
		save_state(state)
		return signal

	# 인버스 보유 중
	if position == "INVERSE":
		# 최저점 갱신
		if net_amount < state["low_net_amount"]:
			state["low_net_amount"] = net_amount
		# 최저점에서 200억 상승
		if net_amount >= state["low_net_amount"] + REVERSE_AMOUNT:
			print(
				f"[ETF 신호] 인버스 -> KODEX200 "
				f"최저점={state['low_net_amount']}, 현재={net_amount}")
			save_state(state)
			return "SWITCH_TO_KODEX200"

	# KODEX200 보유 중
	elif position == "KODEX200":
		# 최고점 갱신
		if net_amount > state["high_net_amount"]:
			state["high_net_amount"] = net_amount
		# 최고점에서 200억 하락
		if net_amount <= state["high_net_amount"] - REVERSE_AMOUNT:
			print(
				f"[ETF 신호] KODEX200 -> 인버스 "
				f"최고점={state['high_net_amount']}, 현재={net_amount}")
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
