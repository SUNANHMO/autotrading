
from etf_state import load_state, save_state


VALID_POSITIONS = ("INVERSE", "KODEX200")


def _clear_order(state):
    state["order_no"] = None
    state["order_type"] = None
    state["order_qty"] = 0
    state["filled_qty"] = 0
    state["remaining_qty"] = 0


def start_initial_buy(target_position, order_no, order_qty):
    """최초 ETF 매수 주문이 접수된 뒤 주문 정보를 저장한다."""

    if target_position not in VALID_POSITIONS:
        raise ValueError("잘못된 ETF 종류")

    state = load_state()

    if state["position"] != "NONE":
        raise RuntimeError("이미 ETF를 보유 중입니다.")

    if state["order_no"] or state["switching"]:
        raise RuntimeError("이미 진행 중인 주문이 있습니다.")

    if not order_no or order_qty <= 0:
        raise ValueError("주문번호와 주문수량을 확인하세요.")

    state["order_no"] = str(order_no)
    state["order_type"] = "BUY"
    state["order_qty"] = int(order_qty)
    state["filled_qty"] = 0
    state["remaining_qty"] = int(order_qty)
    state["target_position"] = target_position

    save_state(state)


def start_switch_sell(target_position, order_no, order_qty):
    """전환을 위해 기존 ETF 매도 주문이 접수된 뒤 호출한다."""

    if target_position not in VALID_POSITIONS:
        raise ValueError("잘못된 전환 대상")

    state = load_state()

    if state["position"] not in VALID_POSITIONS:
        raise RuntimeError("매도할 기존 ETF가 없습니다.")

    if state["position"] == target_position:
        raise RuntimeError("현재 보유 ETF와 전환 대상이 같습니다.")

    if state["order_no"] or state["switching"]:
        raise RuntimeError("이미 진행 중인 주문 또는 전환이 있습니다.")

    if not order_no or order_qty <= 0:
        raise ValueError("주문번호와 주문수량을 확인하세요.")

    state["switching"] = True
    state["target_position"] = target_position

    state["order_no"] = str(order_no)
    state["order_type"] = "SELL"
    state["order_qty"] = int(order_qty)
    state["filled_qty"] = 0
    state["remaining_qty"] = int(order_qty)

    save_state(state)


def record_fill(order_no, fill_qty, fill_id):
    """
    웹소켓 체결 이벤트를 반영한다.
    fill_id는 체결 건마다 고유한 값이어야 한다.
    """

    state = load_state()

    if str(state["order_no"]) != str(order_no):
        return "UNKNOWN_ORDER"

    if not fill_id:
        raise ValueError("중복 체결 방지를 위해 fill_id가 필요합니다.")

    processed = state.get("processed_fill_ids", [])

    if str(fill_id) in processed:
        return "DUPLICATE_FILL"

    fill_qty = int(fill_qty)

    if fill_qty <= 0:
        raise ValueError("체결 수량이 올바르지 않습니다.")

    remaining = int(state["remaining_qty"])

    if fill_qty > remaining:
        raise ValueError("체결 수량이 주문 잔량보다 많습니다.")

    state["filled_qty"] += fill_qty
    state["remaining_qty"] -= fill_qty

    processed.append(str(fill_id))
    state["processed_fill_ids"] = processed[-500:]

    save_state(state)

    if state["remaining_qty"] > 0:
        return "PARTIAL_FILL"

    if state["order_type"] == "SELL":
        return "SELL_FILLED_WAIT_BALANCE"

    if state["order_type"] == "BUY":
        return "BUY_FILLED_WAIT_BALANCE"

    return "UNKNOWN_ORDER_TYPE"


def confirm_sell_balance_zero(balance_qty):
    """
    매도 주문 전량 체결 후 계좌 잔고가 0인지 확인한다.
    0일 때만 반대 ETF 매수를 허용한다.
    """

    state = load_state()

    if not state["switching"]:
        return None

    if state["order_type"] != "SELL":
        return None

    if state["remaining_qty"] != 0:
        return None

    if int(balance_qty) != 0:
        return None

    target = state["target_position"]

    state["position"] = "NONE"
    state["qty"] = 0

    _clear_order(state)

    save_state(state)

    return target


def start_switch_buy(order_no, order_qty):
    """기존 ETF 잔고가 0임을 확인한 후 반대 ETF 매수 주문을 등록한다."""

    state = load_state()

    if not state["switching"]:
        raise RuntimeError("진행 중인 전환이 없습니다.")

    if state["position"] != "NONE" or state["qty"] != 0:
        raise RuntimeError("기존 ETF 잔고가 아직 남아 있습니다.")

    if state["order_no"]:
        raise RuntimeError("기존 주문이 아직 남아 있습니다.")

    if not order_no or order_qty <= 0:
        raise ValueError("주문번호와 주문수량을 확인하세요.")

    state["order_no"] = str(order_no)
    state["order_type"] = "BUY"
    state["order_qty"] = int(order_qty)
    state["filled_qty"] = 0
    state["remaining_qty"] = int(order_qty)

    save_state(state)


def confirm_buy_balance(balance_qty):
    """
    매수 주문 전량 체결 및 계좌 잔고 확인 후 보유 상태를 확정한다.
    """

    state = load_state()

    if state["order_type"] != "BUY":
        return False

    if state["remaining_qty"] != 0:
        return False

    balance_qty = int(balance_qty)

    if balance_qty <= 0:
        return False

    target = state["target_position"]

    if target not in VALID_POSITIONS:
        raise RuntimeError("매수 대상 ETF 정보가 없습니다.")

    state["position"] = target
    state["qty"] = balance_qty

    # 새 보유 방향의 추적 기준을 현재 수급값으로 초기화
    current = state["current_net_amount"]
    state["high_net_amount"] = current
    state["low_net_amount"] = current

    state["switching"] = False
    state["target_position"] = None

    _clear_order(state)

    save_state(state)

    return True
