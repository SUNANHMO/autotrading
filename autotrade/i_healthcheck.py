from d_account import get_account_summary
from e_state import load_state
from telegram_log import log

async def process_check(token, websocket, check_type):
	ok = True
	result = []

	# REST API 확인
	try:
		get_account_summary(token)
		result.append("REST : 정상")
	except Exception as e:
		ok = False
		result.append(f"REST : 오류 ({e})")

	# WebSocket 확인
	if websocket is None:
		ok = False
		result.append("WebSocket : 없음")
	elif websocket.connected:
		result.append("WebSocket : 정상")
	else:
		ok = False
		result.append("WebSocket : 연결끊김")
		try:
			log("WebSocket 재연결 시도")
			await websocket.reconnect()
			if websocket.connected:
				result.append("WebSocket : 복구완료")
			else:
				ok = False
				result.append("WebSocket : 복구실패")
		except Exception as e:
			ok = False
			result.append(f"WebSocket : 복구실패 ({e})")

	# state 확인
	try:
		state = load_state()
		result.append("State : 정상")
	except Exception as e:
		ok = False
		result.append(f"State : 오류 ({e})")
		state = None

	# 15:15 / 15:25 현재가 확인
	if check_type in ("afternoon", "buy"):
		state = load_state()
		if state["holding"]:
			current_price = websocket.price_data.get("current_price",0)
			if current_price > 0:
				result.append(f"현재가 : {current_price:,}")
			else:
				ok = False
				result.append("현재가 : 미수신")
		else:
			result.append("현재가 : 보유종목 없음")

	# 15:25 예상체결가 확인
	if check_type == "buy":
		expected_price = websocket.price_data.get("expected_price", 0)
		if expected_price > 0:
			result.append(f"예상체결가 : {expected_price:,}")
		else:
			ok = False
			result.append("예상체결가 : 미수신")

	# 결과 출력
	title = {
		"morning": "[06:55 시스템 점검]",
		"afternoon": "[15:15 시스템 점검]",
		"buy": "[15:25 시스템 점검]"
	}.get(check_type, "[Health Check]")
	if ok:
		log(title + "\n" + "\n".join(result))
	else:
		log(title + " (이상)\n" + "\n".join(result))
	return ok