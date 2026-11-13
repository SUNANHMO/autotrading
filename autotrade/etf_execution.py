
import time
import logging

from d_account import get_account, _parse_holdings
from etf_state import load_state
from etf_strategy import check_signal
from etf_order_manager import (
    start_switch_sell,
    confirm_sell_balance_zero,
    start_switch_buy,
    confirm_buy_balance,
)

from f_order import (
    etf_sell,
    etf_buy,
    get_etf_buy_qty,
)

from g_websk import get_etf_quote


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
    """실제 계좌 잔고를 조회한다. 조회 실패 시 None."""
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
    """전환 대상 외 다른 종목 보유 여부."""
    for item in holdings:
        if item["qty"] <= 0:
            continue

        if allowed_code and item["code"] == allowed_code:
            continue

        return True

    return False


def _get_fresh_quote(code):
    """3초 이내의 호가만 사용한다."""
    quote = get_etf_quote(code)

    if not isinstance(quote, dict):
        logger.warning("ETF 호가 조회 실패: %s", code)
        return None

    best_bid = int(quote.get("best_bid") or 0)
    best_ask = int(quote.get("best_ask") or 0)

    if best_bid <= 0 or best_ask <= 0:
        logger.warning("ETF 호가값 오류: %s / %s", best_bid, best_ask)
        return None

    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
    }


def start_etf_switch(token, signal):
    """
    전환 신호가 발생했을 때 기존 ETF 매도 주문을 시작한다.
    실제 계좌 수량과 내부 상태 수량이 일치해야 주문한다.
    """
    target_position = SIGNAL_TO_POSITION.get(signal)

    if not target_position:
        return False

    state = load_state()

    current_position = state.get("position")
    current_code = POSITION_TO_CODE.get(current_position)

    if not current_code:
        logger.warning("전환 매도 중단: 현재 보유 방향이 올바르지 않음")
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

    quote = _get_fresh_quote(current_code)

    if quote is None:
        return False

    # 매도는 최우선 매도호가 지정가
    sell_price = quote["best_ask"]

    order_no = etf_sell(
        token,
        current_code,
        actual_qty,
        sell_price,
    )

    if not order_no:
        logger.error("ETF 전환 매도 주문 접수 실패")
        return False

    started = start_switch_sell(
        target_position,
        order_no,
        actual_qty,
    )

    if not started:
        logger.critical(
            "매도 주문은 접수됐지만 내부 상태 등록 실패. "
            "추가 주문 금지 및 수동 확인 필요: %s",
            order_no,
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


def advance_etf_switch(token):
    """
    체결 이벤트 이후 계좌 잔고를 확인하고 다음 단계로 진행한다.
    스케줄러에서 반복 호출한다.
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
    order_qty = int(state.get("order_qty") or 0)
    filled_qty = int(state.get("filled_qty") or 0)
    remaining_qty = int(state.get("remaining_qty") or 0)

    # --------------------------------------------------
    # 1단계: 기존 ETF 매도 전량 체결 후 실제 잔고 확인
    # --------------------------------------------------
    if order_type == "SELL":
        if order_qty <= 0 or filled_qty != order_qty or remaining_qty != 0:
            return

        current_position = state.get("position")
        current_code = POSITION_TO_CODE.get(current_position)
        target_position = state.get("target_position")
        target_code = POSITION_TO_CODE.get(target_position)

        if not current_code or not target_code:
            logger.error("ETF 전환 중단: 보유/목표 종목 상태 오류")
            return

        holdings = _get_account_holdings(token)

        if holdings is None:
            return

        actual_qty = _get_holding_qty(holdings, current_code)

        # 기존 ETF 잔고가 0주가 아니면 매수 금지
        if actual_qty != 0:
            logger.info(
                "ETF 매도 체결 완료, 계좌 잔고 확인 대기: %s주",
                actual_qty,
            )
            return

        if _has_other_holding(holdings):
            logger.error("ETF 전환 매수 중단: 계좌에 다른 종목 잔고 존재")
            return

        confirmed_target = confirm_sell_balance_zero(actual_qty)

        if confirmed_target != target_position:
            logger.error("ETF 매도 잔고 0 확인 또는 상태 전환 실패")
            return

        # --------------------------------------------------
        # 2단계: 반대 ETF 매수
        # --------------------------------------------------
        quote = _get_fresh_quote(target_code)

        if quote is None:
            logger.warning("반대 ETF 매수 대기: 유효한 호가 없음")
            return

        buy_price = quote["best_bid"]

        buy_qty = get_etf_buy_qty(
            token,
            target_code,
            buy_price,
        )

        if not buy_qty or buy_qty <= 0:
            logger.error("반대 ETF 매수 수량 계산 실패")
            return

        buy_order_no = etf_buy(
            token,
            target_code,
            buy_qty,
            buy_price,
        )

        if not buy_order_no:
            logger.error("반대 ETF 매수 주문 접수 실패")
            return

        started = start_switch_buy(
            buy_order_no,
            buy_qty,
        )

        if not started:
            logger.critical(
                "매수 주문은 접수됐지만 내부 상태 등록 실패. "
                "추가 주문 금지 및 수동 확인 필요: %s",
                buy_order_no,
            )
            return

        logger.info(
            "ETF 전환 매수 주문 접수: %s / 수량=%s / 가격=%s / 주문번호=%s",
            target_code,
            buy_qty,
            buy_price,
            buy_order_no,
        )

        return

    # --------------------------------------------------
    # 3단계: 반대 ETF 매수 전량 체결 후 실제 잔고 확인
    # --------------------------------------------------
    if order_type == "BUY":
        if order_qty <= 0 or filled_qty != order_qty or remaining_qty != 0:
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
            logger.error("ETF 매수 완료 확인 실패: 다른 종목 잔고 존재")
            return

        if confirm_buy_balance(actual_qty):
            logger.info(
                "ETF 전환 완료: %s / 실제 보유=%s주",
                target_position,
                actual_qty,
            )
        else:
            logger.error("ETF 매수 잔고 확인 후 내부 상태 반영 실패")
