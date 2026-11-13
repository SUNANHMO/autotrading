import time
import logging

from d_account import get_account, _parse_holdings
from etf_state import load_state
from etf_order_manager import (
	start_switch_sell,
	confirm_sell_balance_zero,
	start_switch_buy,
	confirm_buy_balance,
	mark_switch_buy_unknown,
)

from f_order import (
	etf_sell,
	etf_buy,
	get_etf_buy_qty,
)


logger = logging.getLogger(__name__)

POSITION_TO_CODE = {
	"KODEX200": "069500",
	"INVERSE": "114800",
}

SIGNAL_TO_POSITION = {
	"SWITCH_TO_KODEX200": "KODEX200",
	"SWITCH_TO_INVERSE": "INVERSE",
}

BALANCE_CHECK_INTERVAL = 3
_last_balance_check = 0


def _get_account_holdings(token):
	"""실제 계좌 잔고 조회. 실패 시 None."""
	try:
		account = get_account(token)

		if not isinstance(account, dict):
			logger.error("ETF 계좌 조회 실패")
			return None

		return _parse_holdings(account)

	except Exception:
		logger.exception("ETF 계좌 잔고 조회 중 오류")
		return None


def _get_holding_qty(holdings, code):
	for item in holdings:
		if item["code"] == code:
			return int(item["qty"])

	return 0


def _has_other_holding(holdings, allowed_code=None):
	"""허용된 종목 외 다른 종목 보유 여부."""
	for item in holdings:
		if item["qty"] <= 0:
			continue

		if allowed_code and item["code"] == allowed_code:
			continue

		return True

	return False


def _get_fresh_quote(websocket, code):
	"""WebSocketClient의 3초 이내 호가 조회."""
	if websocket is None or not websocket.connected:
		logger.warning("ETF WebSocket 연결 없음")
		return None

	try:
		quote = websocket.get_etf_quote(
			code,
			max_age_seconds=3,
		)
	except Exception:
		logger.exception("ETF 호가 조회 중 오류: %s", code)
		return None

	if not isinstance(quote, dict):
		logger.warning("ETF 호가 조회 실패: %s", code)
		return None

	try:
		best_bid = int(quote.get("best_bid") or 0)
		best_ask = int(quote.get("best_ask") or 0)
	except (ValueError, TypeError):
		logger.warning("ETF 호가 숫자 변환 실패: %s", code)
		return None

	if best_bid <= 0 or best_ask <= 0:
		logger.warning("ETF 호가값 오류: %s", code)
		return None

	return {
		"best_bid": best_bid,
		"best_ask": best_ask,
	}


def start_etf_switch(token, signal, websocket):
	"""
	전환 신호 발생 시 기존 ETF 매도 주문을 시작한다.
	실제 계좌 수량과 내부 상태 수량이 일치해야 한다.
	"""

	target_position = SIGNAL_TO_POSITION.get(signal)

	if not target_position:
		return False

	state = load_state()

	current_position = state.get("position")
	current_code = POSITION_TO_CODE.get(current_position)

	if not current_code:
		logger.warning("전환 매도 중단: 현재 보유 방향 오류")
		return False

	if target_position == current_position:
		return False

	if (
		state.get("order_no")
		or state.get("switching")
		or state.get("closing_started")
	):
		logger.warning("전환 매도 중단: 기존 주문 또는 전환 진행 중")
		return False

	holdings = _get_account_holdings(token)

	if holdings is None:
		return False

	actual_qty = _get_holding_qty(holdings, current_code)
	internal_qty = int(state.get("qty") or 0)

	if actual_qty <= 0 or actual_qty != internal_qty:
		logger.error(
			"전환 매도 중단: 계좌 수량과 내부 수량 불일치 "
			"(계좌=%s, 내부=%s)",
			actual_qty,
			internal_qty,
		)
		return False

	if _has_other_holding(holdings, current_code):
		logger.error("전환 매도 중단: 다른 종목 보유 확인")
		return False

	quote = _get_fresh_quote(websocket, current_code)

	if quote is None:
		return False

	# 기존 전략: 최우선 매도호가 지정가
	sell_price = quote["best_ask"]

	try:
		order_no = etf_sell(
			token,
			current_code,
			actual_qty,
			sell_price,
		)
	except Exception:
		logger.exception("ETF 전환 매도 주문 요청 중 오류")
		return False

	if not order_no:
		logger.error("ETF 전환 매도 주문 접수 실패")
		return False

	try:
		start_switch_sell(
			target_position,
			order_no,
			actual_qty,
		)
	except Exception:
		logger.critical(
			"매도 주문 접수 후 내부 상태 등록 실패. "
			"추가 주문 금지 및 수동 확인 필요: %s",
			order_no,
			exc_info=True,
		)
		return False

	logger.info(
		"ETF 전환 매도 주문 접수: %s / 수량=%s / 가격=%s / 주문번호=%s",
		current_code,
		actual_qty,
		sell_price,
		order_no,
	)

	return True


def _submit_switch_buy(token, websocket, target_position):
	"""
	SELL_DONE 상태에서 반대 ETF 매수 주문을 시도한다.

	호가 또는 매수 가능 금액 조회가 실패하면
	SELL_DONE 상태를 유지하고 다음 실행 주기에 재시도한다.
	"""

	target_code = POSITION_TO_CODE.get(target_position)

	if not target_code:
		logger.error("ETF 전환 매수 중단: 목표 종목 오류")
		return False

	# 매수 직전 실제 계좌 잔고 재확인
	holdings = _get_account_holdings(token)

	if holdings is None:
		logger.warning("ETF 전환 매수 대기: 계좌 조회 실패")
		return False

	if _has_other_holding(holdings):
		logger.error(
			"ETF 전환 매수 중단: 계좌에 다른 종목 잔고 존재"
		)
		return False

	quote = _get_fresh_quote(websocket, target_code)

	if quote is None:
		logger.warning(
			"ETF 전환 매수 대기: 유효한 호가 없음 (%s)",
			target_code,
		)
		return False

	# 기존 전략: 최우선 매수호가 지정가
	buy_price = quote["best_bid"]

	try:
		buy_qty = get_etf_buy_qty(
			token,
			target_code,
			buy_price,
		)
	except Exception:
		logger.exception("ETF 매수 가능 수량 조회 오류")
		return False

	if not buy_qty or buy_qty <= 0:
		logger.warning(
			"ETF 전환 매수 대기: 매수 가능 수량 없음"
		)
		return False

	try:
		buy_order_no = etf_buy(
			token,
			target_code,
			buy_qty,
			buy_price,
		)
	except Exception:
		mark_switch_buy_unknown()
		logger.exception("ETF 전환 매수 주문 접수 여부 불명확")
		return False

	if not buy_order_no:
		mark_switch_buy_unknown()
		logger.critical(
			"ETF 매수 주문번호 확인 실패. "
			"중복 주문 방지를 위해 자동 재주문 차단"
		)
		return False

	try:
		start_switch_buy(
			buy_order_no,
			buy_qty,
		)
	except Exception:
		mark_switch_buy_unknown()
		logger.critical(
			"매수 주문 접수 후 내부 상태 등록 실패. "
			"수동 확인 필요: %s",
			buy_order_no,
			exc_info=True,
		)
		return False

	logger.info(
		"ETF 전환 매수 주문 접수: %s / 수량=%s / 가격=%s / 주문번호=%s",
		target_code,
		buy_qty,
		buy_price,
		buy_order_no,
	)

	return True


def advance_etf_switch(token, websocket):
	"""
	체결 이벤트 이후 계좌 잔고를 확인하고 전환을 진행한다.

	SELL:
		매도 전량 체결 및 계좌 잔고 0 확인

	SELL_DONE:
		반대 ETF 매수 시도. 호가나 매수 가능 금액 조회 실패 시 재시도

	BUY:
		매수 전량 체결 및 계좌 잔고 확인
	"""

	global _last_balance_check

	now = time.monotonic()

	if now - _last_balance_check < BALANCE_CHECK_INTERVAL:
		return

	_last_balance_check = now

	state = load_state()

	if not state.get("switching"):
		return

	order_type = state.get("order_type")

	# --------------------------------------------------
	# 1단계: 기존 ETF 매도 전량 체결 후 잔고 확인
	# --------------------------------------------------
	if order_type == "SELL":

		order_qty = int(state.get("order_qty") or 0)
		filled_qty = int(state.get("filled_qty") or 0)
		remaining_qty = int(state.get("remaining_qty") or 0)

		if (
			order_qty <= 0
			or filled_qty != order_qty
			or remaining_qty != 0
		):
			return

		current_position = state.get("position")
		current_code = POSITION_TO_CODE.get(current_position)
		target_position = state.get("target_position")

		if not current_code or target_position not in POSITION_TO_CODE:
			logger.error("ETF 전환 중단: 보유/목표 종목 상태 오류")
			return

		holdings = _get_account_holdings(token)

		if holdings is None:
			return

		actual_qty = _get_holding_qty(holdings, current_code)

		if actual_qty != 0:
			logger.info(
				"ETF 매도 체결 완료, 계좌 잔고 확인 대기: %s주",
				actual_qty,
			)
			return

		if _has_other_holding(holdings):
			logger.error("ETF 전환 매수 중단: 다른 종목 잔고 존재")
			return

		confirmed_target = confirm_sell_balance_zero(actual_qty)

		if confirmed_target != target_position:
			logger.error("ETF 매도 잔고 0 확인 또는 상태 전환 실패")
			return

		logger.info(
			"ETF 기존 매도 완료: SELL_DONE / 다음 매수 대상=%s",
			target_position,
		)

		# 여기서 바로 매수하지 않고 다음 실행 주기에 SELL_DONE 처리
		return

	# --------------------------------------------------
	# 2단계: 매도 완료 후 반대 ETF 매수 대기
	# --------------------------------------------------
	if order_type == "SELL_DONE":

		target_position = state.get("target_position")

		if target_position not in POSITION_TO_CODE:
			logger.error("ETF 매수 대기 중단: 목표 종목 상태 오류")
			return

		_submit_switch_buy(
			token,
			websocket,
			target_position,
		)

		return

	# --------------------------------------------------
	# 3단계: 반대 ETF 매수 전량 체결 후 실제 잔고 확인
	# --------------------------------------------------
	if order_type == "BUY":

		order_qty = int(state.get("order_qty") or 0)
		filled_qty = int(state.get("filled_qty") or 0)
		remaining_qty = int(state.get("remaining_qty") or 0)

		if (
			order_qty <= 0
			or filled_qty != order_qty
			or remaining_qty != 0
		):
			return

		target_position = state.get("target_position")
		target_code = POSITION_TO_CODE.get(target_position)

		if not target_code:
			logger.error("ETF 매수 잔고 확인 실패: 목표 종목 오류")
			return

		holdings = _get_account_holdings(token)

		if holdings is None:
			return

		actual_qty = _get_holding_qty(holdings, target_code)

		if actual_qty != filled_qty:
			logger.info(
				"ETF 매수 전량 체결 후 계좌 잔고 확인 대기 "
				"(계좌=%s, 체결=%s)",
				actual_qty,
				filled_qty,
			)
			return

		if _has_other_holding(holdings, target_code):
			logger.error(
				"ETF 매수 완료 확인 실패: 다른 종목 잔고 존재"
			)
			return

		if confirm_buy_balance(actual_qty):
			logger.info(
				"ETF 전환 완료: %s / 실제 보유=%s주",
				target_position,
				actual_qty,
			)
		else:
			logger.error("ETF 매수 잔고 확인 후 내부 상태 반영 실패")

		return

	if order_type == "BUY_SUBMIT_UNKNOWN":
	logger.critical(
		"ETF 매수 주문 접수 여부 불명확. "
		"중복 주문 방지를 위해 자동 진행 중단"
	)
	return

	logger.warning(
		"ETF 전환 중 알 수 없는 주문 상태: %s",
		order_type,
	)
