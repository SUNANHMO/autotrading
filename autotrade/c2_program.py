import requests
import time

from datetime import datetime
from telegram_log import log
from e_state import load_state, save_state, clear_state
from a_config import WS_URL, REST_HOST

def parse_amount(value):
	value = value.strip()

	if value.startswith("--"):
		return -int(value[2:])

	if value.startswith("+"):
		return int(value[1:])

	return int(value)

#키움API
def fn_kt00004(token, data, cont_yn='N', next_key=''):
	host = REST_HOST
	endpoint = '/api/dostk/acnt'
	url = host + endpoint
	headers = {
		'Content-Type': 'application/json;charset=UTF-8',
		'authorization': f'Bearer {token}',
		'cont-yn': cont_yn,
		'next-key': next_key,
		'api-id': 'kt00004'}
	response = requests.post(url, headers=headers, json=data)
	result = response.json()
	return (
		result,
		response.headers.get("cont-yn"),
		response.headers.get("next-key"))
def fn_ka10001(token, data):
	host = REST_HOST
	endpoint = '/api/dostk/stkinfo'
	url = host + endpoint
	headers = {
		'Content-Type': 'application/json;charset=UTF-8',
		'authorization': f'Bearer {token}',
		'api-id': 'ka10001'}
	response = requests.post(url, headers=headers, json=data)
	result = response.json()
	return result
def fn_ka10007(token, data, cont_yn='N', next_key=''):
	host = REST_HOST
	endpoint = '/api/dostk/mrkcond'
	url = host + endpoint
	headers = {
		'Content-Type': 'application/json;charset=UTF-8',
		'authorization': f'Bearer {token}',
		'cont-yn': cont_yn,
		'next-key': next_key,
		'api-id': 'ka10007'}
	response = requests.post(url, headers=headers, json=data)
	if response.status_code != 200:
		raise Exception(response.text)
	result = response.json()
	# API 오류도 체크
	if result.get("return_code", 0) != 0:
		raise Exception(result)
	return result
def fn_ka10086(token, data, cont_yn='N', next_key=''):
	host = REST_HOST
	endpoint = '/api/dostk/mrkcond'
	url = host + endpoint
	headers = {
		'Content-Type': 'application/json;charset=UTF-8',
		'authorization': f'Bearer {token}',
		'cont-yn': cont_yn,
		'next-key': next_key,
		'api-id': 'ka10086'}
	response = requests.post(url,headers=headers,json=data)
	result = response.json()
	return (
		result,
		response.headers.get('cont-yn'),
		response.headers.get('next-key'))
def fn_ka90013(token, data, cont_yn='N', next_key=''):
	host = REST_HOST
	endpoint = '/api/dostk/mrkcond'
	url = host + endpoint
	headers = {
		'Content-Type': 'application/json;charset=UTF-8',
		'authorization': f'Bearer {token}',
		'cont-yn': cont_yn,
		'next-key': next_key,
		'api-id': 'ka90013'}
	response = requests.post(url, headers=headers, json=data)
	result = response.json()
	return (
		result,
		response.headers.get('cont-yn'),
		response.headers.get('next-key'))

#Program data
def get_program_data(token, code, days, date):
	time.sleep(0.3)
	params = {
		'amt_qty_tp': '1',
		'stk_cd': code,
		'date': date}

	all_data = []

	cont_yn = 'N'
	next_key = ''

	while True:

		result, cont_yn, next_key = fn_ka90013(
			token=token,
			data=params,
			cont_yn=cont_yn,
			next_key=next_key)

		if 'stk_daly_prm_trde_trnsn' not in result:
			return None

		page_data = result['stk_daly_prm_trde_trnsn']

		all_data.extend(page_data)

		if len(all_data) >= days:
			return all_data[:days]

		if cont_yn != 'Y':
			return all_data

		time.sleep(1)
def get_program_data_500(token, code, date):
	return get_program_data(token, code, 500, date)

#Market, Day, Envelop
def get_market_info(token, code):
	return fn_ka10007(token, {"stk_cd": code})
def get_market_cap(token, code, date=None):
	result = get_market_info(token, code)
	price = abs(parse_amount(result["cur_prc"]))
	shares = int(result["flo_stkcnt"]) * 1000 # flo_stkcnt는 천주 단위
	return price * shares
def get_day_data(token, code, days, date):

	params = {'stk_cd': code, 'qry_dt': date, 'indc_tp': '0'}
	all_data = []
	cont_yn = 'N'
	next_key = ''

	while True:
		result, cont_yn, next_key = fn_ka10086(
			token=token,
			data=params,
			cont_yn=cont_yn,
			next_key=next_key)

		if 'daly_stkpc' not in result:
			return None

		page_data = result['daly_stkpc']
		all_data.extend(page_data)

		if len(all_data) >= days: # 필요한 개수만 모이면 종료
			return all_data[:days]

		if cont_yn != 'Y': # 마지막 페이지면 종료
			return all_data

		time.sleep(1)
def get_stock_info(token, code):
	params = {"stk_cd": code}
	result = fn_ka10001(token=token, data=params)
	if result.get("return_code") != 0:
		return None
	return int(result["flo_stk"]) * 1000	# 천주 → 주
def find_last_crossup(token, code, date):
	data = get_day_data(token, code, 500, date)

	if data is None:
		return None
	
	data = data[::-1] # 오래된 날짜부터 계산하기 위해 뒤집기
	ma40 = [] # 40일 이동평균 계산

	for i in range(len(data)):
		if i < 39:
			ma40.append(None)
			continue
		total = 0
		for j in range(i - 39, i + 1):
			total += abs(int(data[j]["close_pric"]))
		ma40.append(total / 40)

	last_cross = None
	above = False

	for i in range(39, len(data)):
		high = abs(int(data[i]["high_pric"]))
		upper = ma40[i] * 1.30
		if not above and high >= upper:
			last_cross = data[i]["date"]
			above = True
		elif above and high < upper:
			above = False
	return last_cross

#4단계 필터
def is_20day_max(token, code, date):

	data = get_program_data(token, code, 20, date)

	if data is None:
		print(code, "프로그램 데이터 없음")
		return False

	print(code, "조회건수:", len(data))

	today = abs(parse_amount(data[0]["prm_netprps_amt"]))

	for item in data[1:]:

		value = abs(parse_amount(item["prm_netprps_amt"]))

		if value >= today:
			print(code, "20일 탈락")
			return False

	print(code, "20일 통과")
	return True
def is_370day_max(program_data, code):

	if not program_data:
		print(code, "데이터 없음")
		return False
	
	data = program_data[:371]

	print(code, "조회건수:", len(data))

	today = abs(parse_amount(data[0]["prm_netprps_amt"]))

	for item in data[1:]:

		value = abs(parse_amount(item["prm_netprps_amt"]))

		if value >= today:
			print(code, "370일 탈락")
			return False

	print(code, "370일 통과")
	return True
def is_first_after_crossup(token, code, program_data_500, date):

	cross_date = find_last_crossup(token, code, date)

	if cross_date is None:
		print(code, "돌파일 없음")
		return False

	if program_data_500 is None:
		return False

	# 오래된 날짜 -> 오늘 순으로 변경
	data = program_data_500[::-1]

	# 돌파 이후 날짜부터 검사
	for i in range(len(data)):

		if data[i]["dt"] < cross_date:
			continue

		today_value = abs(parse_amount(data[i]["prm_netprps_amt"]))

		start = max(0, i - 370)

		max_value = 0

		# 직전 370일 최대값 계산
		for j in range(start, i):

			value = abs(parse_amount(data[j]["prm_netprps_amt"]))

			if value > max_value:
				max_value = value

		# 이 날이 370일 최대인 첫 번째 날인가?
		if today_value > max_value:

			# 그 첫 번째 날이 오늘이면 True
			if i == len(data) - 1:
				print(code, "돌파 이후 최초 370일 최대")
				return True

			# 오늘이 아니면 이미 예전에 발생한 것
			print(code, "이미 돌파 이후 최초 370일 최대 발생")
			return False

	print(code, "조건 불충족")
	return False
def is_short_overheat_warning(day_data, listed_shares):

	"""
	day_data : 오래된 날짜 -> 최근 날짜 순
	listed_shares : 상장주식수(주)

	return
	-------
	True  : 오늘 단기과열(예고)
	False : 해당없음
	"""

	if len(day_data) < 50:
		return False

	# ---------------------------------------
	# 회전율 / 변동성 계산
	# ---------------------------------------

	turnover = []
	volatility = []

	for d in day_data:

		high = float(d["high_pric"])
		low = float(d["low_pric"])
		close = float(d["close_pric"])
		volume = float(d["trde_qty"])

		turnover.append(volume / listed_shares)

		if high + low == 0:
			volatility.append(0)
		else:
			volatility.append(
				(high - low) / ((high + low) / 2))

	# ---------------------------------------
	# D0 관리
	# ---------------------------------------

	d0_close = None
	d0_index = None

	for i in range(40, len(day_data)):

		close = float(day_data[i]["close_pric"])
		prev_close = float(day_data[i - 1]["close_pric"])
		ma40 = (sum(float(x["close_pric"]) for x in day_data[i-40:i])/ 40)
		turnover40 = sum(turnover[i-40:i]) / 40
		turnover2 = sum(turnover[i-1:i+1]) / 2
		volatility40 = sum(volatility[i-40:i]) / 40
		volatility2 = sum(volatility[i-1:i+1]) / 2

		A = (
			close >= ma40 * 1.3
			and turnover2 >= turnover40 * 6
			and volatility2 >= volatility40 * 1.5
			and close > prev_close)

		# D0 만료
		if d0_index is not None and i > d0_index + 10:

			print(f"D0 만료 : {day_data[d0_index]['date']}")

			d0_close = None
			d0_index = None

		# D0 없으면 새로 저장
		if d0_close is None:

			if A:
				d0_close = close
				d0_index = i

				print(f"D0 발생 : {day_data[i]['date']} 종가={close}")

			continue

		# -------------------------------
		# 예고조건
		# -------------------------------

		if A and close > d0_close:

			print(
				f"예고 발생 : {day_data[i]['date']} "
				f"D0={d0_close} "
				f"현재={close}")

			if i == len(day_data) - 1:
				return True

	return False
def is_trading_day(token):
	today = datetime.today().strftime("%Y%m%d")
	data = get_day_data(token, "005930", 1, today)
	if data is None or len(data) == 0:
		return False
	return data[0]["date"] == today

#계좌관리
def get_account_info(token, date=None):
	params = {"qry_tp": "1","dmst_stex_tp": "KRX"}
	result, _, _ = fn_kt00004(token=token,data=params)
	#print("계좌조회 응답:")
	print(result)
	if result.get("return_code", 0) != 0:
		return None
	return result
def get_cash(token=None, date=None, account=None):

	if account is None:
		account = get_account_info(token, date)

	if account is None:
		return None

	return int(account["prsm_dpst_aset_amt"])
def get_asset(token=None, date=None, account=None):

	if account is None:
		account = get_account_info(token, date)

	if account is None:
		return None

	return int(account["aset_evlt_amt"])
def get_holding(token=None, date=None, account=None):

	if account is None:
		account = get_account_info(token, date)

	if account is None:
		return None

	holdings = account.get("stk_acnt_evlt_prst", [])

	if len(holdings) == 0:
		return None

	item = holdings[0]

	return {
		"code": item["stk_cd"],
		"name": item["stk_nm"],
		"qty": int(item["rmnd_qty"]),
		"buy_price": int(item["avg_prc"]),
	}
def has_holding(token=None, date=None, account=None):

	return get_holding(
		token=token,
		date=date,
		account=account
	) is not None
def update_account(token, date):
	account = get_account_info(token, date)
	holding = get_holding(account=account)

	if holding is None:
		clear_state()
		return account

	state = load_state()
	state["holding"] = True
	state["code"] = holding["code"]
	state["name"] = holding["name"]
	state["qty"] = holding["qty"]
	state["buy_price"] = holding["buy_price"]

	save_state(state)

	return account
