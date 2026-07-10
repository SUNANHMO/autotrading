import time
import requests

from a_config import APP_KEY, SECRET_KEY
from a_config import REST_HOST
from telegram import log

def get_token():
	endpoint = "/oauth2/token"
	url = REST_HOST + endpoint
	headers = {"Content-Type": "application/json;charset=UTF-8"}
	params = {
		"grant_type": "client_credentials",
		"appkey": APP_KEY,
		"secretkey": SECRET_KEY}
	while True:
		try:
			response = requests.post(url, headers=headers, json=params, timeout=5)
			result = response.json()
			token = result.get("token")
			if token:
				log("Access Token 발급 성공")
				return token
			log(f"토큰 발급 실패 : {result}")
		except Exception as e:
			log(f"토큰 발급 오류 : {e}")
		log("5초 후 재시도")
		time.sleep(5)

if __name__ == "__main__":
	token = get_token()
	print(token)