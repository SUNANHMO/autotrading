# 키움 REST API 설정
IS_MOCK = True  # 모의투자 : Ture / 실전투자 : False

if IS_MOCK:
	REST_HOST = "https://mockapi.kiwoom.com" # 모의투자
	WS_URL = "wss://mockapi.kiwoom.com:10000/api/dostk/websocket"
	ACCOUNT_NO = "8130274111"
	APP_KEY = "EZt0oXFHaixfgrESIODTuiij6VMTA1z8leZFu_0bqGA"
	SECRET_KEY = "uXj7-Di6L7iuK6Q1wDuee-bpdoAnefRUEUVzS6Jz-tA"
else:
	REST_HOST = "https://api.kiwoom.com" # 실전투자
	WS_URL = "wss://api.kiwoom.com:10000/api/dostk/websocket"
	ACCOUNT_NO = "6618028811"
	APP_KEY = "PObxSf_yWNbRgWVlM7fzRkwbgE-bfjcETJyT4HYmPJ4"
	SECRET_KEY = "490D2XhJt3_mIhX4VuXu_pZLnlhQE3Z0fWK0LzuBU-E"
	
BUY_RATIO = 2.48  # 2.5배 미수 대신 수수료/오차 고려
BUY_PRICE_BUFFER_RATE = 0.01 # 예) 1.0 = 예상체결가 + 1%
TAKE_PROFIT_RATE = 0.05   # (익절) +5%
STOP_LOSS_RATE = -0.001	# (손절) -4%, 부호는 무시됨(abs 사용)

TELEGRAM_TOKEN = "8932924634:AAESjWOelv4d8Leotu4eIycKH1hWAEVWPL0"
TELEGRAM_CHAT_ID = "7887391551"

TEST_DATE = None # 테스트 날짜 : 운영 시 None 사용

# 스케줄 시간
TOKEN_TIME = "07:00:00"
NXT_TAKE_PROFIT_TIME = "08:00:01"
KRX_TAKE_PROFIT_TIME = "08:30:01"
MONITOR_START_TIME = "09:00:00"
FORCE_SELL_TIME = "15:19:00"
MONITOR_END_TIME = "15:20:00"
SEARCH_TIME = "15:20:05"
BUY_TIME = "15:29:59"
CANCEL_TAKE_PROFIT_TIME = "15:31:00"

#Health체크타임
MORNING_CHECK_TIME = "06:55:00"
AFTERNOON_CHECK_TIME = "15:15:00"
BUY_CHECK_TIME = "15:27:00"