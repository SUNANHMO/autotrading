from d_account import get_account_summary
from e_state import load_state
from telegram_log import log

async def process_check(token, websocket, check_type):
	ok = True
	result = []
	# 1. REST API 확인
	if check_type != "morning":
		try:
			summary = get_account_summary(token)
			if summary["account"] is not None:
				result.append("REST")
			else:
				ok = False
				result.append("★REST")
		except Exception as e:
			ok = False
			result.append("★REST")
			print(f"REST check error: {e}")

	# 2. WebSocket 확인
	if websocket is None:
		ok = False
		result.append("★WEBSK")  # WebSocket 객체 없음
	elif websocket.connected:
		result.append("WEBSK")  # WebSocket 정상
	else:
		# 여기서 reconnect() 하지 않음
		# g_websk.py의 run()이 자동 재연결 담당
		ok = False
		result.append("★WEBSK")  # WebSocket 연결 끊김

	# 3. State 확인
	try:
		state = load_state()
		result.append("STATE")
	except Exception as e:
		ok = False
		result.append("★STATE")
		print(f"State check error: {e}")
		state = None

	# 4. 15:15 / 15:25 현재가 확인
	if check_type in ("afternoon", "buy"):
		if state is not None and state["holding"]:
			current_price = websocket.price_data.get("current_price",0)
			if current_price > 0:
				result.append(
					f"C_{current_price:,}")
			else:
				ok = False
				result.append("★C")  # 현재가 미수신
		else:
			result.append("No_C")  # 보유종목 없음

	# 5. 15:25 예상체결가 확인
	if check_type == "buy":
		if websocket is not None and websocket.current_code:
			expected_price = websocket.price_data.get("expected_price",0)
			if expected_price > 0:
				result.append(f"E_{expected_price:,}")
			else:
				ok = False
				result.append("★E")  # 예상체결가 미수신
		else:
			result.append("No_E")  # 검사 대상 없음

	# 6. 결과 출력
	if ok:
		print("SYS")
	else:
		log(" ".join(result))
	return ok