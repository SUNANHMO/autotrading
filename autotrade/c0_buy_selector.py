from datetime import datetime
import time

from telegram_log import log

from a_config import TEST_DATE
from c2_program import (get_program_data_500, get_market_info, get_day_data, get_previous_trading_date,
	is_20day_max, is_370day_max, is_first_after_crossup, is_short_overheat_warning, parse_amount,)

def get_buy_code(token, codes):

	reference_date = (TEST_DATE or datetime.today().strftime("%Y%m%d"))
	test_date = get_previous_trading_date(token, reference_date)
	if test_date is None:
		log("★NO_PREVIOUS_TRADING_DATE")
		return None
	print(f"Reference Date: {reference_date}")
	print(f"Program Data Date: {test_date}")

	# 후보 종목별 시총 저장
	candidate_market_caps = {}
	for code in codes:

		# (1단계) 최근 20일 프로그램 최대
		if not is_20day_max(token, code, test_date):
			continue

		# (2단계) 단기과열(예고) 제외
		day_data = get_day_data(token, code, 60, test_date)
		if day_data is None or len(day_data) < 50:
			continue
		day_data.reverse() # 최신 -> 과거 순으로 변경
		market_info = get_market_info(token, code) # 상장주식수는 단기과열 검증에 필요하므로 여기서는 기존처럼 종목정보 조회가 필요함
		time.sleep(1.0) # API 호출 직후 1초 대기
		if market_info is None:
			continue
		try:
			listed_shares = int(market_info["flo_stkcnt"]) * 1000
		except (KeyError, TypeError, ValueError):
			print(f"{code} Market Info Error")
			continue
		if is_short_overheat_warning(day_data, listed_shares):
			print(f"Excluded (Short-term Overheating): {code}")
			continue

		# (3단계) 최근 370일 최대 검증
		program_data = get_program_data_500(token,code,test_date)
		if program_data is None or len(program_data) == 0:
			continue
		if not is_370day_max(program_data, code):
			continue

		# (4단계) 최초 양수 370일 최대 돌파 검증
		if not is_first_after_crossup(token,code,program_data,test_date):
			continue

		# ★ 여기까지 통과한 종목만 최종 후보
		try:
			price = abs(parse_amount(market_info["cur_prc"]))
			market_cap = price * listed_shares
		except (KeyError, TypeError, ValueError):
			print(f"{code} Market Cap Calculation Error")
			continue
		# 후보 종목과 시총 저장
		candidate_market_caps[code] = market_cap
		print(f"Candidate Selected: {code}")
		print(f"Market Cap: {code} = {market_cap:,}")
		time.sleep(1.0) # API 유량 보호 > 후보 종목의 시총 확인 후 1초 대기

	if candidate_market_caps:
		# 시총 오름차순 정렬
		sorted_candidates = sorted(candidate_market_caps.items(), key=lambda x: x[1])

		# 텔레그램 전송
		candidate_codes = [code for code, market_cap in sorted_candidates]
		log(
			"FINAL CANDIDATES\n"
			+ ", ".join(candidate_codes))

		# 시총이 가장 작은 종목을 최종 매수 종목으로 선택
		buy_code = sorted_candidates[0][0]
		print(f"Final Buy Stock: {buy_code}")
		print(
			f"Final Market Cap: "
			f"{candidate_market_caps[buy_code]:,}")

		return buy_code

	print("No Final Candidates Found")
	log("FINAL CANDIDATES NONE")
	return None