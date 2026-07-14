from d_account import get_account_summary
from e_state import load_state
from telegram_log import log

async def process_check(token, websocket, check_type):
	ok = True
	result = []

	# REST API 확인
	try:
		get_account_summary(token)
		result.append("R") #REST : 정상
	except Exception as e:
		ok = False
		result.append("★REST") #f"REST : 오류 ({e})"
		print(e)

	# WebSocket 확인
	if websocket is None:
		ok = False
		result.append("★WEBSK") #WebSocket : 없음
	elif websocket.connected:
		result.append("W") #WebSocket : 정상
	else:
		try:
			print("Attempting to reconnect WebSocket")  # WebSocket 재연결 시도
			await websocket.reconnect()

			if websocket.connected:
				result.append("W")
			else:
				ok = False
				result.append("★WEBSK")

		except Exception as e:
			ok = False
			result.append("★WEBSK")
			print(e)

	# state 확인
	try:
		state = load_state()
		result.append("S")
	except Exception as e:
		ok = False
		result.append("★STATE")
		print(e)
		state = None

	# 15:15 / 15:25 현재가 확인
	if check_type in ("afternoon", "buy"):
		state = load_state()
		if state["holding"]:
			current_price = websocket.price_data.get("current_price",0)
			if current_price > 0:
				result.append(f"C_{current_price:,}") # C=현재가
			else:
				ok = False
				result.append("★C") #현재가 : 미수신
		else:
			result.append("No_C") #현재가 : 보유종목 없음

	# 15:25 예상체결가 확인
	if check_type == "buy":
		if websocket.current_code:
			expected_price = websocket.price_data.get("expected_price", 0)

			if expected_price > 0:
				result.append(f"E_{expected_price:,}") #예상체결가
			else:
				ok = False
				result.append("★E") #예상체결가 : 미수신
		else:
			result.append("No_E") #예상체결가 : 검사 대상 없음
			
	# 결과 출력
	if ok:
		print("SYS") # 정상
	else:
		log(" ".join(result)) # 오류발생

	return ok