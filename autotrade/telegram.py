import requests

from a_config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID


def send_message(message):

	if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
		print("텔레그램 설정 없음")
		print(message)
		return False

	url = (
		f"https://api.telegram.org/"
		f"bot{TELEGRAM_TOKEN}/sendMessage"	)

	params = {"chat_id": TELEGRAM_CHAT_ID,"text": message}

	try:
		response = requests.post(url, params=params, timeout=5)
		result = response.json()

		if result.get("ok"):
			return True

		print("텔레그램 전송 실패")
		print(result)
		return False

	except Exception as e:
		print(f"텔레그램 오류 : {e}")
		return False


def log(message):
	print(message)
	send_message(message)