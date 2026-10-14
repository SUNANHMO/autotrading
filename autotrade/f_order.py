
import math
import requests
from datetime import datetime

from telegram_log import log
from a_config import (BUY_RATIO, TAKE_PROFIT_RATE, REST_HOST, STOP_LOSS_RATE,)
from c2_program import (get_trading_days_passed, get_day_data, parse_amount,)
from e_state import load_state, save_state


# 키움 REST API
def _request(token, api_id, data):
	url = REST_HOST + "/api/dostk/ordr"
	headers = {
		"Content-Type": "application/json;charset=UTF-8",
		"authorization": f"Bearer {token}",
		"cont-yn": "N",
		"next-key": "",
		"api-id": api_id,}
	response = requests.post(url, headers=headers, json=data, timeout=10,)
	response.raise_for_status()
	return response.json()
def fn_kt00011(token, data, cont_yn="N", next_key=""):
	url = REST_HOST + "/api/dostk/acnt"
	headers = {
		"Content-Type": "application/json;charset=UTF-8",
		"authorization": f"Bearer {token}",
		"cont-yn": cont_yn,
		"next-key": next_key,
		"api-id": "kt00011",}
	response = requests.post(url, headers=headers, json=data, timeout=10,)
	response.raise_for_status()
	return response.json()
def fn_kt10000(token, data, cont_yn="N", next_key=""):
	return _request(token, "kt10000", data)
def fn_kt10001(token, data, cont_yn="N", next_key=""):
	return _request(token, "kt10001", data)
def fn_kt10003(token, data, cont_yn="N", next_key=""):
	return _request(token, "kt10003", data)

# 매수 수량 및 호가
def get_buy_qty(token, code, buy_price):
	if buy_price <= 0:
		return 0

	result = fn_kt00011(token, {"stk_cd": code, "uv": str(buy_price),},)
	amount = result.get("profa_40ord_alow_amt")
	if amount is None:
		log("★BUY_QTY")
		print("주문 가능 금액 조회 실패:", result)
		return 0
	order_amount = int(int(amount) * (BUY_RATIO / 2.5))
	return order_amount // buy_price

def get_upper_price(price):
	price = math.ceil(price)
	if price < 2_000:
		unit = 1
	elif price < 5_000:
		unit = 5
	elif price < 20_000:
		unit = 10
	elif price < 50_000:
		unit = 50
	elif price < 200_000:
		unit = 100
	elif price < 500_000:
		unit = 500
	else:
		unit = 1_000
	return math.ceil(price / unit) * unit

# 매수 주문
def buy(token, code, buy_price):
	state = load_state()

	# 실제 보유 중이면 신규 매수 금지
	if state.get("holding") and int(state.get("qty") or 0) > 0:
		log("SKIP_BUY_HOLDING")
		return None

	# 기존 매수 주문의 체결/취소 상태가 정리되지 않았다면, 중복 매수 주문을 제출하지 않음
	if state.get("buy_order_no"):
		log("SKIP_BUY_ORDER_EXISTS")
		return None
	if buy_price <= 0:
		log("★BUY_PRICE")
		return None
	qty = get_buy_qty(token, code, buy_price)
	if qty <= 0:
		log("★BUY_QTY_ZERO")
		return None
	data = {
		"dmst_stex_tp": "KRX",
		"stk_cd": code,
		"ord_qty": str(qty),
		"ord_uv": str(buy_price),
		"trde_tp": "0",
		"cond_uv": "",}
	try:
		result = fn_kt10000(token, data)
	except Exception as e:
		log(f"★BUY_API_{type(e).__name__}")
		print("매수 주문 API 오류:", e)
		return None
	order_no = result.get("ord_no")
	if not order_no:
		log("★BUY_ORDER")
		print("매수 주문 실패:", result)
		return None

	# 주문 접수는 보유 상태를 의미하지 않음. 실제 체결 수량은 g_websk.py의 체결 이벤트에서 반영해야 함.
	state["holding"] = False
	state["candidate_code"] = code
	state["code"] = code
	state["buy_order_no"] = order_no
	state["buy_order_qty"] = qty
	state["buy_filled_qty"] = 0
	state["buy_remaining_qty"] = qty
	state["buy_fill_amount"] = 0
	state["position_origin"] = "new"
	state["opening_price"] = 0
	state["opening_high_cancelled"] = False
	save_state(state)
	print(f"매수 주문 접수: code={code}, qty={qty}, price={buy_price}, order_no={order_no}")
	return order_no

# 매수 미체결 잔량 취소
def cancel_buy_order(token):
	state = load_state()
	order_no = state.get("buy_order_no")
	code = state.get("candidate_code") or state.get("code")
	if not order_no or not code:
		return None
	data = {
		"dmst_stex_tp": "KRX",
		"orig_ord_no": order_no,
		"stk_cd": code,
		"cncl_qty": "0",}
	try:
		result = fn_kt10003(token, data)
	except Exception as e:
		log(f"★BUY_CANCEL_API_{type(e).__name__}")
		print("매수 취소 API 오류:", e)
		return None
	cancel_order_no = result.get("ord_no")
	if not cancel_order_no:
		log("★BUY_CANCEL")
		print("매수 취소 결과 확인 필요:", result)
		return None

	# 취소 접수 이후에도 실제 잔량과 체결 수량은 체결 이벤트 및 계좌 조회로 다시 확인해야 함.
	state["buy_order_no"] = None
	state["buy_remaining_qty"] = 0
	state["opening_high_cancelled"] = True
	save_state(state)
	print(f"매수 잔량 취소 접수: original={order_no}, cancel={cancel_order_no}")
	return cancel_order_no

# 익절 주문
def take_profit(token, market):
	state = load_state()
	qty = int(state.get("qty") or 0)
	if not state.get("holding") or qty <= 0:
		return None

	# 기존 익절 주문이 있으면 중복 주문 금지
	if state.get("take_profit_order_no"):
		print("익절 주문이 이미 등록되어 있습니다.")
		return state["take_profit_order_no"]
	buy_price = int(state.get("buy_price") or 0)
	if buy_price <= 0:
		log("★TP_BUY_PRICE")
		return None
	target_price = get_upper_price(buy_price * (1 + TAKE_PROFIT_RATE))
	data = {
		"dmst_stex_tp": market,
		"stk_cd": state["code"],
		"ord_qty": str(qty),
		"ord_uv": str(target_price),
		"trde_tp": "0",
		"cond_uv": "",}
	try:
		result = fn_kt10001(token, data)
	except Exception as e:
		log(f"★TP_API_{type(e).__name__}")
		print("익절 주문 API 오류:", e)
		return None
	order_no = result.get("ord_no")
	if not order_no:
		log("★TP_ORDER")
		print("익절 주문 실패:", result)
		return None
	state["take_profit_order_no"] = order_no
	state["profit_market"] = market
	save_state(state)

	print(
		f"익절 주문 접수: code={state['code']}, "
		f"qty={qty}, price={target_price}, market={market}")
	return order_no

def take_profit_nxt(token):
	return take_profit(token, "NXT")

def take_profit_krx(token):
	return take_profit(token, "KRX")

# 익절 주문 취소
def cancel_take_profit(token):
	state = load_state()
	order_no = state.get("take_profit_order_no")
	if not order_no:
		return None
	market = state.get("profit_market")

	if not market or not state.get("code"):
		log("★TP_CANCEL_STATE")
		return None
	data = {
		"dmst_stex_tp": market,
		"orig_ord_no": order_no,
		"stk_cd": state["code"],
		"cncl_qty": "0",}
	try:
		result = fn_kt10003(token, data)
	except Exception as e:
		log(f"★TP_CANCEL_API_{type(e).__name__}")
		print("익절 취소 API 오류:", e)
		return None
	cancel_order_no = result.get("ord_no")
	if not cancel_order_no:
		log("★CANCEL")
		print("익절 취소 결과 확인 필요:", result)
		return None
	state["take_profit_order_no"] = None
	state["profit_market"] = None
	save_state(state)
	print(f"익절 취소 접수: original={order_no}, cancel={cancel_order_no}")
	return cancel_order_no

# 시장가 매도
def market_sell(token):
	state = load_state()
	qty = int(state.get("qty") or 0)
	if not state.get("holding") or qty <= 0:
		return None

	# 익절 주문 취소에 실패하면 중복 매도 위험이 있으므로 시장가 매도 주문을 진행하지 않음.
	if state.get("take_profit_order_no"):
		cancel_order_no = cancel_take_profit(token)
		if not cancel_order_no:
			log("★CANCEL_SELL_BLOCKED")
			print("익절 취소 확인 실패: 시장가 매도를 중단합니다.")
			return None
	data = {
		"dmst_stex_tp": "KRX",
		"stk_cd": state["code"],
		"ord_qty": str(qty),
		"ord_uv": "",
		"trde_tp": "3",
		"cond_uv": "",}
	try:
		result = fn_kt10001(token, data)
	except Exception as e:
		log(f"★SELL_API_{type(e).__name__}")
		print("시장가 매도 API 오류:", e)
		return None
	order_no = result.get("ord_no")
	if not order_no:
		log("★SELL_ORDER")
		print("시장가 매도 주문 실패:", result)
		return None
	state["sell_order_no"] = order_no
	save_state(state)
	print(f"시장가 매도 접수: code={state['code']}, qty={qty}, order_no={order_no}")
	return order_no

# 강제 매도 조건
def should_force_sell(token):
	state = load_state()

	if not state.get("holding") or int(state.get("qty") or 0) <= 0:
		return False
	buy_date = state.get("buy_date")
	if buy_date:
		days = get_trading_days_passed(token, buy_date, datetime.today().strftime("%Y%m%d"),)
		if days is not None and days >= 2:
			print("FORCE SELL : HOLDING DAYS")
			return True
	data = get_day_data(token, state["code"], 1, datetime.today().strftime("%Y%m%d"),)
	if not data:
		return False
	today = data[0]
	high = abs(parse_amount(today["high_pric"]))
	low = abs(parse_amount(today["low_pric"]))
	buy_price = int(state.get("buy_price") or 0)
	if buy_price <= 0:
		return False
	if high >= buy_price * (1 + abs(TAKE_PROFIT_RATE)):
		print("FORCE SELL : TAKE PROFIT MISSED")
		return True
	if low <= buy_price * (1 - abs(STOP_LOSS_RATE)):
		print("FORCE SELL : STOP LOSS MISSED")
		return True
	return False
