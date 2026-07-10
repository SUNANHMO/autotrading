import asyncio 
import websockets
import json
from telegram import log
from a_config import WS_URL, REST_HOST

SOCKET_URL = WS_URL  # 접속 URL

class WebSocketClient:
	def __init__(self, uri, token):
		self.uri = uri
		self.token = token
		self.websocket = None
		self.connected = False
		self.keep_running = True

	# WebSocket 서버에 연결합니다.
	async def connect(self):
		try:
			self.websocket = await websockets.connect(self.uri)
			self.connected = True
			print("서버와 연결을 시도 중입니다.")

			# 로그인 패킷
			param = {'trnm': 'LOGIN', 'token': self.token}

			print('실시간 시세 서버로 로그인 패킷을 전송합니다.')
			# 웹소켓 연결 시 로그인 정보 전달
			await self.send_message(message=param)

		except Exception as e:
			print(f'Connection error: {e}')
			self.connected = False

	# 서버에 메시지를 보냅니다. 연결이 없다면 자동으로 연결합니다.
	async def send_message(self, message):
		if not self.connected:
			await self.connect()  # 연결이 끊어졌다면 재연결
		if self.connected:
			# message가 문자열이 아니면 JSON으로 직렬화
			if not isinstance(message, str):
				message = json.dumps(message)

		await self.websocket.send(message)
		print(f'Message sent: {message}')

	# 서버에서 오는 메시지를 수신하여 출력합니다.
	async def receive_messages(self):
		while self.keep_running:
			try:
				# 서버로부터 수신한 메시지를 JSON 형식으로 파싱
				response = json.loads(await self.websocket.recv())

				# 메시지 유형이 LOGIN일 경우 로그인 시도 결과 체크
				if response.get('trnm') == 'LOGIN':
					if response.get('return_code') != 0:
						print('로그인 실패하였습니다. : ', response.get('return_msg'))
						await self.disconnect()
					else:
						print('로그인 성공하였습니다.')
						print('조건검색 목록조회 패킷을 전송합니다.')
						# 로그인 패킷
						param = {'trnm': 'CNSRLST'}
						await self.send_message(message=param)

				elif response.get('trnm') == 'CNSRLST':

					if response.get("return_code") != 0:
						print("조건검색 목록 조회 실패 :", response.get("return_msg"))
						await self.disconnect()
						return []

					await self.send_message({
						'trnm':'CNSRREQ',
						'seq':'5',
						'search_type':'0',
						'stex_tp':'K',
						'cont_yn':'N',
						'next_key':''})

				# 메시지 유형이 PING일 경우 수신값 그대로 송신
				elif response.get('trnm') == 'PING':
					await self.websocket.send(json.dumps(response))

				# 조건검색 결과를 받으면 종료
				if response.get('trnm') == 'CNSRREQ':

					data = response.get("data")

					# 검색 결과가 없는 경우
					if not data:
						print("검색 결과 없음")
						await self.disconnect()
						return []

					codes = []

					for item in data:
						code = item["9001"].replace("A", "")
						codes.append(code)

					await self.disconnect()
					return codes

			except websockets.ConnectionClosed:
				print('Connection closed by the server')
				self.connected = False
				await self.websocket.close()

	# WebSocket 실행
	async def run(self):
		await self.connect()
		codes = await self.receive_messages()
		return codes

	# WebSocket 연결 종료
	async def disconnect(self):
		self.keep_running = False
		if self.connected and self.websocket:
			await self.websocket.close()
			self.connected = False
			print('Disconnected from WebSocket server')

async def search_pgm(token):
	websocket_client = WebSocketClient(SOCKET_URL, token)
	codes = await websocket_client.run()
	print(f"검색종목: {len(codes)}개")
	return codes