from etf_state import load_state, save_state


VALID_POSITIONS = ("INVERSE", "KODEX200")


def _clear_order(state):
	"""일반 주문 관련 상태만 초기화한다."""
	state["order_no"] = None
	state["order_type"] = None
	state["order_qty"] = 0
	state["filled_qty"] = 0
	state["remaining_qty"] = 0


def _save(state):
	save_state(state)
	return state


def _valid_order(order_no, order_qty):
	try:
		qty = int(order_qty or 0)
	except (ValueError, TypeError):
		return False

	return (
		order_no is not None
		and str(order_no).strip() != ""
		and qty > 0
	)


def start_initial_buy(target_position, order_no, order_qty):
	"""최초 ETF 매수 주문 등록."""

	if target_position not in VALID_POSITIONS:
		raise ValueError("잘못된 ETF 매수 대상입니다.")

	if not _valid_order(order_no, order_qty):
		raise ValueError("잘못된 ETF 주문 정보입니다.")

	state = load_state()

	if state.get("position") != "NONE":
		raise RuntimeError("이미 ETF 보유 상태입니다.")

	if state.get("order_no") or state.get("switching"):
		raise RuntimeError("진행 중인 ETF 주문이 있습니다.")

	if state.get("closing_started"):
		raise RuntimeError("마감 정리 상태에서는 신규 매수할 수 없습니다.")

	state["order_no"] = str(order_no)
	state["order_type"] = "BUY"
	state["order_qty"] = int(order_qty)
	state["filled_qty"] = 0
	state["remaining_qty"] = int(order_qty)

	state["target_position"] = target_position
	state["switching"] = False

	return _save(state)


def start_switch_sell(target_position, order_no, order_qty):
	"""ETF 방향 전환을 위한 기존 ETF 매도 주문 등록."""

	if target_position not in VALID_POSITIONS:
		raise ValueError("잘못된 전환 대상입니다.")

	if not _valid_order(order_no, order_qty):
		raise ValueError("잘못된 ETF 매도 주문 정보입니다.")

	state = load_state()

	current_position = state.get("position")

	if current_position not in VALID_POSITIONS:
		raise RuntimeError("현재 ETF 보유 상태가 아닙니다.")

	if current_position == target_position:
		raise RuntimeError("현재 보유 ETF와 전환 대상이 같습니다.")

	if state.get("order_no") or state.get("switching"):
		raise RuntimeError("이미 진행 중인 ETF 주문이 있습니다.")

	if state.get("closing_started"):
		raise RuntimeError("마감 정리 중에는 방향 전환할 수 없습니다.")

	order_qty = int(order_qty)

	if order_qty != int(state.get("qty") or 0):
		raise RuntimeError("매도 주문 수량과 내부 보유 수량이 다릅니다.")

	state["switching"] = True
	state["target_position"] = target_position

	state["order_no"] = str(order_no)
	state["order_type"] = "SELL"
	state["order_qty"] = order_qty
	state["filled_qty"] = 0
	state["remaining_qty"] = order_qty

	return _save(state)


def start_closing_sell(order_no, order_qty):
	"""장 마감 ETF 정리 매도 주문 등록."""

	if not _valid_order(order_no, order_qty):
		raise ValueError("잘못된 마감 매도 주문 정보입니다.")

	state = load_state()

	if state.get("position") not in VALID_POSITIONS:
		raise RuntimeError("청산할 ETF 보유 상태가 아닙니다.")

	if state.get("order_no"):
		raise RuntimeError("기존 ETF 주문이 남아 있습니다.")

	if state.get("switching"):
		raise RuntimeError("ETF 방향 전환 중입니다.")

	if state.get("closing_started"):
		raise RuntimeError("마감 매도 주문이 이미 시작되었습니다.")

	order_qty = int(order_qty)

	if order_qty != int(state.get("qty") or 0):
		raise RuntimeError("마감 매도 수량과 내부 보유 수량이 다릅니다.")

	state["closing_started"] = True
	state["closing_order_no"] = str(order_no)

	state["order_no"] = str(order_no)
	state["order_type"] = "CLOSE"
	state["order_qty"] = order_qty
	state["filled_qty"] = 0
	state["remaining_qty"] = order_qty

	state["target_position"] = None

	return _save(state)


def record_fill(order_no, fill_qty, fill_id):
	"""실시간 체결 이벤트 기록 및 중복 체결 방지."""

	state = load_state()

	if not order_no or str(order_no) != str(state.get("order_no")):
		return "UNKNOWN_ORDER"

	if not fill_id:
		return "INVALID_FILL_ID"

	try:
		fill_qty = int(fill_qty or 0)
	except (ValueError, TypeError):
		return "INVALID_FILL_QTY"

	if fill_qty <= 0:
		return "INVALID_FILL_QTY"

	composite_fill_id = f"{order_no}:{fill_id}"

	processed = state.get("processed_fill_ids", [])

	if composite_fill_id in processed:
		return "DUPLICATE_FILL"

	remaining_qty = int(state.get("remaining_qty") or 0)

	if fill_qty > remaining_qty:
		return "INVALID_FILL_QTY"

	state["filled_qty"] = (
		int(state.get("filled_qty") or 0) + fill_qty
	)

	state["remaining_qty"] = remaining_qty - fill_qty

	processed.append(composite_fill_id)
	state["processed_fill_ids"] = processed[-500:]

	if state["remaining_qty"] > 0:
		result = "PARTIAL_FILL"

	elif state.get("order_type") == "SELL":
		result = "SELL_FILLED_WAIT_BALANCE"

	elif state.get("order_type") == "BUY":
		result = "BUY_FILLED_WAIT_BALANCE"

	elif state.get("order_type") == "CLOSE":
		result = "CLOSE_FILLED_WAIT_BALANCE"

	else:
		result = "UNKNOWN_ORDER_TYPE"

	_save(state)

	return result


def confirm_sell_balance_zero(balance_qty):
	"""
	전환 매도 전량 체결 및 실제 잔고 0 확인.

	기존 주문 정보는 지우되 전환 상태는 SELL_DONE으로 보존한다.
	"""

	state = load_state()

	if not state.get("switching"):
		return None

	if state.get("order_type") != "SELL":
		return None

	order_qty = int(state.get("order_qty") or 0)
	filled_qty = int(state.get("filled_qty") or 0)
	remaining_qty = int(state.get("remaining_qty") or 0)

	if order_qty <= 0 or filled_qty != order_qty:
		return None

	if remaining_qty != 0:
		return None

	if int(balance_qty or 0) != 0:
		return None

	target_position = state.get("target_position")

	if target_position not in VALID_POSITIONS:
		return None

	state["position"] = "NONE"
	state["qty"] = 0

	_clear_order(state)

	# 핵심: 매도 완료 후에도 전환 상태를 유지한다.
	state["order_type"] = "SELL_DONE"
	state["switching"] = True
	state["target_position"] = target_position

	_save(state)

	return target_position


def start_switch_buy(order_no, order_qty):
	"""매도 완료 상태에서 반대 ETF 매수 주문 등록."""

	if not _valid_order(order_no, order_qty):
		raise ValueError("잘못된 ETF 매수 주문 정보입니다.")

	state = load_state()

	if not state.get("switching"):
		raise RuntimeError("ETF 방향 전환 상태가 아닙니다.")

	if state.get("order_type") != "SELL_DONE":
		raise RuntimeError("기존 ETF 매도 완료 상태가 아닙니다.")

	if state.get("position") != "NONE":
		raise RuntimeError("기존 ETF 보유 상태가 아직 해제되지 않았습니다.")

	if state.get("order_no"):
		raise RuntimeError("기존 ETF 주문이 남아 있습니다.")

	if int(state.get("qty") or 0) != 0:
		raise RuntimeError("기존 ETF 수량이 0이 아닙니다.")

	if state.get("target_position") not in VALID_POSITIONS:
		raise RuntimeError("전환 대상 ETF가 올바르지 않습니다.")

	order_qty = int(order_qty)

	state["order_no"] = str(order_no)
	state["order_type"] = "BUY"
	state["order_qty"] = order_qty
	state["filled_qty"] = 0
	state["remaining_qty"] = order_qty

	return _save(state)


def confirm_buy_balance(balance_qty):
	"""매수 전량 체결 및 실제 계좌 잔고 확인."""

	state = load_state()

	if state.get("order_type") != "BUY":
		return False

	order_qty = int(state.get("order_qty") or 0)
	filled_qty = int(state.get("filled_qty") or 0)
	remaining_qty = int(state.get("remaining_qty") or 0)
	balance_qty = int(balance_qty or 0)

	if order_qty <= 0:
		return False

	if filled_qty != order_qty:
		return False

	if remaining_qty != 0:
		return False

	if balance_qty != filled_qty:
		return False

	target_position = state.get("target_position")

	if target_position not in VALID_POSITIONS:
		return False

	current_net_amount = int(
		state.get("current_net_amount") or 0
	)

	state["position"] = target_position
	state["qty"] = balance_qty

	state["high_net_amount"] = current_net_amount
	state["low_net_amount"] = current_net_amount

	state["switching"] = False
	state["target_position"] = None

	_clear_order(state)

	_save(state)

	return True


def confirm_closing_balance_zero(balance_qty):
	"""마감 청산 전량 체결 및 실제 ETF 잔고 0 확인."""

	state = load_state()

	if not state.get("closing_started"):
		return False

	if state.get("order_type") != "CLOSE":
		return False

	order_qty = int(state.get("order_qty") or 0)
	filled_qty = int(state.get("filled_qty") or 0)
	remaining_qty = int(state.get("remaining_qty") or 0)

	if order_qty <= 0 or filled_qty != order_qty:
		return False

	if remaining_qty != 0:
		return False

	if int(balance_qty or 0) != 0:
		return False

	state["position"] = "NONE"
	state["qty"] = 0

	state["switching"] = False
	state["target_position"] = None

	state["closing_started"] = True

	_clear_order(state)

	return _save(state)
