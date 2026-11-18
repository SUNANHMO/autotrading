# 키움 REST API 설정
IS_MOCK = False  # 모의투자 : True / 실전투자 : False

if IS_MOCK:
	REST_HOST = "https://mockapi.kiwoom.com" # 모의투자
	WS_URL = "wss://mockapi.kiwoom.com:10000/api/dostk/websocket"
	ACCOUNT_NO = "8130274111"
	APP_KEY = "k5Az_Pee3pTKXJW0AhzOPeKAYYbVDzXyMsj0j3dnq5E"
	SECRET_KEY = "e9p3cUHG7qPJnLur4gVVGg29ILNRKQtGVRNWnHkInaE"
else:
	REST_HOST = "https://api.kiwoom.com" # 실전투자
	WS_URL = "wss://api.kiwoom.com:10000/api/dostk/websocket"
	ACCOUNT_NO = "6618028811"
	APP_KEY = "PObxSf_yWNbRgWVlM7fzRkwbgE-bfjcETJyT4HYmPJ4"
	SECRET_KEY = "490D2XhJt3_mIhX4VuXu_pZLnlhQE3Z0fWK0LzuBU-E"
	
BUY_RATIO = 2.48  # 2.5배 미수 대신 수수료/오차 고려
BUY_PRICE_BUFFER_RATE = 0.01 # 예) 1.0 = 예상체결가 + 1%
TAKE_PROFIT_RATE = 0.05   # (익절) +5%
STOP_LOSS_RATE = -0.04	# (손절) -4%, 부호는 무시됨(abs 사용)

TELEGRAM_TOKEN = "8932924634:AAESjWOelv4d8Leotu4eIycKH1hWAEVWPL0"
TELEGRAM_CHAT_ID = "7887391551"

TEST_DATE = None # 테스트 날짜 : 운영 시 None 사용

# 거래소 일정 지연(평소 00:00:00, 수능일 01:00:00)
PLUS_TIME = "00:00:00"

from datetime import datetime, timedelta

def shift_time(base, seconds=0, *, compact=False):
    """기준 시각 + 상대 초 + PLUS_TIME. 문자열 HH:MM:SS 또는 HHMMSS 반환."""
    offset = sum(int(x) * unit for x, unit in zip(PLUS_TIME.split(":"), (3600, 60, 1)))
    dt = datetime.strptime(base, "%H:%M:%S") + timedelta(seconds=seconds + offset)
    return dt.strftime("%H%M%S" if compact else "%H:%M:%S")

def relative_time(adjusted_base, seconds=0, *, compact=False):
    """이미 PLUS_TIME이 적용된 설정 시각에 상대 초만 더한다."""
    dt = datetime.strptime(adjusted_base, "%H:%M:%S") + timedelta(seconds=seconds)
    return dt.strftime("%H%M%S" if compact else "%H:%M:%S")

# 스케줄 시간
TOKEN_TIME = shift_time("07:00:00")
SEARCH_TIME = shift_time("07:30:00")
NXT_TAKE_PROFIT_TIME = shift_time("08:00:00")
KRX_TAKE_PROFIT_TIME = shift_time("08:30:00")
BUY_TIME = shift_time("08:59:55")
MONITOR_START_TIME = shift_time("08:59:55")
FORCE_SELL_TIME = shift_time("15:25:00")
MONITOR_END_TIME = shift_time("15:20:00")
CANCEL_TAKE_PROFIT_TIME = shift_time("15:31:00") #"15:31:00"

#Health체크타임
MORNING_CHECK_TIME = shift_time("06:55:00")
BUY_CHECK_TIME = shift_time("08:55:00")
AFTERNOON_CHECK_TIME = shift_time("15:20:05")

# 전환 기준: 200억 원 (단위: 백만 원)
REVERSE_AMOUNT = 0.2

ETF_FLOW_MAX_AGE_SECONDS = 30
