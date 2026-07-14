import requests
import math
from datetime import datetime
from telegram_log import log

from a_config import BUY_RATIO, TAKE_PROFIT_RATE, WS_URL, REST_HOST, STOP_LOSS_RATE
from c2_program import get_day_data
from e_state import load_state, save_state

#키움API
def fn_kt00011(token, data, cont_yn='N', next_key=''): # 증거금율별주문가능수량조회요청
	host = REST_HOST # 실전투자
	endpoint = '/api/dostk/acnt'
	url =  host + endpoint
	headers = {
		'Content-Type': 'application/json;charset=UTF-8',
		'authorization': f'Bearer {token}', 
		'cont-yn': cont_yn, 
		'next-key': next_key, 
		'api-id': 'kt00011'}
	response = requests.post(url, headers=headers, json=data)
	return response.json()
def fn_kt10000(token, data, cont_yn='N', next_key=''): # 매수
	host = REST_HOST # 실전투자
	endpoint = '/api/dostk/ordr'
	url =  host + endpoint
	headers = {
		'Content-Type': 'application/json;charset=UTF-8', 
		'authorization': f'Bearer {token}', 
		'cont-yn': cont_yn, 
		'next-key': next_key, 
		'api-id': 'kt10000'}
	response = requests.post(url, headers=headers, json=data)
	return response.json()
def fn_kt10001(token, data, cont_yn='N', next_key=''): # 매도
	host = REST_HOST # 실전투자
	endpoint = '/api/dostk/ordr'
	url =  host + endpoint
	headers = {
		'Content-Type': 'application/json;charset=UTF-8', 
		'authorization': f'Bearer {token}', 
		'cont-yn': cont_yn, 
		'next-key': next_key, 
		'api-id': 'kt10001'}
	response = requests.post(url, headers=headers, json=data)
	return response.json()
def fn_kt10003(token, data, cont_yn='N', next_key=''): # 취소
	host = REST_HOST # 실전투자
	endpoint = '/api/dostk/ordr'
	url =  host + endpoint
	headers = {
		'Content-Type': 'application/json;charset=UTF-8', 
		'authorization': f'Bearer {token}', 
		'cont-yn': cont_yn, 
		'next-key': next_key, 
		'api-id': 'kt10003'}
	response = requests.post(url, headers=headers, json=data)
	return response.json()

#기초수식
def get_buy_qty(token, code, buy_price):
	data = {"stk_cd": code, "uv": str(buy_price)}
	result = fn_kt00011(token, data)
	order_amount = int(result["profa_40ord_alow_amt"])
	order_amount = int(order_amount * (BUY_RATIO / 2.5))
	qty = order_amount // buy_price
	return qty
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
		unit = 1000

	return math.ceil(price / unit) * unit

#주문관리
def buy(token, code, buy_price):
	qty = get_buy_qty(token=token,code=code,buy_price=buy_price)
	if qty <= 0:
		return None
	data = {
		"dmst_stex_tp": "KRX",
		"stk_cd": code,
		"ord_qty": str(qty),
		"ord_uv": str(buy_price),
		"trde_tp": "0",		# 보통가
		"cond_uv": ""
	}
	result = fn_kt10000(token, data)
	order_no = result.get("ord_no")
	if order_no:
		state = load_state()
		state["holding"] = False
		state["buy_order_no"] = order_no
		save_state(state)
		return order_no
	return None
def take_profit(token, market):
	state = load_state()
	if not state["holding"]:
		return None
	target_price = get_upper_price(state["buy_price"] * (1 + TAKE_PROFIT_RATE))
	data = {
		"dmst_stex_tp": market,
		"stk_cd": state["code"],
		"ord_qty": str(state["qty"]),
		"ord_uv": str(target_price),
		"trde_tp": "0",
		"cond_uv": ""}
	result = fn_kt10001(token, data)
	order_no = result.get("ord_no")
	if order_no:
		state["take_profit_order_no"] = order_no
		state["profit_market"] = market
		save_state(state)
		return order_no
	return None
def take_profit_nxt(token):
	return take_profit(token, "NXT")
def take_profit_krx(token):
	return take_profit(token, "KRX")
def cancel_take_profit(token):
	state = load_state()

	order_no = state["take_profit_order_no"]

	print(f"Attempting to cancel Take-Profit, Order No: {order_no}")  # 익절 취소 시도 주문번호 :

	if order_no is None:
		return None

	data = {
		"dmst_stex_tp": state["profit_market"],
		"orig_ord_no": order_no,
		"stk_cd": state["code"],
		"cncl_qty": "0"}

	print(f"Take-Profit Cancel Request Data: {data}")  # 익절 취소 요청 데이터 :

	result = fn_kt10003(token, data)

	print(f"Take-Profit Cancel Response: {result}")  # 익절 취소 응답 :

	if result.get("ord_no"):
		state["take_profit_order_no"] = None
		state["profit_market"] = None
		save_state(state)

		return result["ord_no"]

	return None

def market_sell(token):
	state = load_state()
	if not state["holding"]:
		return None
	if state["take_profit_order_no"] is not None:
		cancel_order_no = cancel_take_profit(token)
		if cancel_order_no:
			print(f"Take-Profit Cancelled Successfully: {cancel_order_no}")  # 익절 취소 완료 :
		else:
			log("★CANCEL")
			print("Failed to cancel Take-Profit order - Check existing order status")  # 익절 주문 취소 실패 - 기존 주문 확인 필요
	data = {
		"dmst_stex_tp": "KRX",
		"stk_cd": state["code"],
		"ord_qty": str(state["qty"]),
		"ord_uv": "",
		"trde_tp": "3",
		"cond_uv": ""}
	result = fn_kt10001(token, data)
	order_no = result.get("ord_no")
	if order_no:
		state["sell_order_no"] = order_no
		save_state(state)
		return order_no
	return None
	
def should_force_sell(token):
	state = load_state()
	if not state["holding"]:
		return False
	if state["holding_days"] >= 2: # D+2 강제청산
		return True
	# 오늘 고가/저가 조회
	today = datetime.today().strftime("%Y%m%d")
	day_data = get_day_data(token, state["code"], 1, today)
	if day_data is None or len(day_data) == 0:
		return False
	high_price = int(day_data[0]["high_pric"])
	low_price = int(day_data[0]["low_pric"])
	buy_price = state["buy_price"]
	
	print(f"buy_price={buy_price}")
	print(f"high_price={high_price}")
	print(f"low_price={low_price}")
	print(f"take_profit_price={buy_price * (1 + TAKE_PROFIT_RATE)}")
	print(f"stop_loss_price={buy_price * (1 - STOP_LOSS_RATE)}")
	# 오늘 익절가를 찍었는데 아직 보유
	if high_price >= buy_price * (1 + TAKE_PROFIT_RATE):
		return True
	# 오늘 손절가를 찍었는데 아직 보유
	if low_price <= buy_price * (1 - STOP_LOSS_RATE):
		return True
	return False
