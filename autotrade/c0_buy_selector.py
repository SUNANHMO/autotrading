import asyncio
from datetime import datetime
from telegram_log import log

from a_config import TEST_DATE
from c1_search import search_pgm
from c2_program import (
	get_program_data_500, get_market_cap, get_day_data, get_stock_info,
	is_20day_max, is_370day_max, is_first_after_crossup, is_short_overheat_warning)
	
def get_buy_code(token):
	
	test_date = TEST_DATE or datetime.today().strftime("%Y%m%d")
	codes = asyncio.run(search_pgm(token))
	candidate = []

	for code in codes:
			
		# (1단계) 최근 20일 프로그램 최대
		if not is_20day_max(token, code, test_date): 
			continue

		# (2단계) 단기과열(예고) 제외
		day_data = get_day_data(token, code, 60, test_date) 
		if day_data is None or len(day_data) < 50:
			continue
		day_data.reverse() # 최신 -> 과거 순이므로 뒤집기
		
		listed_shares = get_stock_info(token, code)
		if listed_shares is None:
			continue
		if is_short_overheat_warning(day_data, listed_shares):
			print(f"단기과열(예고) 제외 : {code}")
			continue

		# (3단계) 프로그램 데이터 조회 및 최근 370일 최대 검증
		program_data = get_program_data_500(token, code, test_date) 
		if program_data is None or len(program_data) == 0:
			continue

		if not is_370day_max(program_data, code): 
			continue

		# (4단계) 최초돌파 검증
		if not is_first_after_crossup(token, code, program_data, test_date): 
			continue

		candidate.append(code)
		print(f"후보 선정 : {code}")

	# 최종 후보 종목 선정 및 출력
	if candidate:
		buy_code = min(candidate,key=lambda code: get_market_cap(token, code, test_date))
		print(f"최종 매수종목 : {buy_code}")
		return buy_code

	print("최종 후보 없음")
	return None