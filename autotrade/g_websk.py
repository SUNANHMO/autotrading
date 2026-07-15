import asyncio
import json
import time
import websockets
from telegram_log import log

from datetime import datetime
from b_auth import get_token
from e_state import load_state, save_state, clear_state, get_force_sell_date
from a_config import WS_URL, STOP_LOSS_RATE

class WebSocketClient:
	def __init__(self, token):
		self.last_alive = time.time()
		self.uri = WS_URL
		self.token = token
		self.websocket = None
		self.connected = False	
		self.price_data = {
			"current_price": 0,	  # 0B에서 수신
			"expected_price": 0}  # 0H에서 수신
		self.order_data = {
			"order_no": None,	 # 9203 주문체결 정보
			"status": None,		 # 913
			"remain_qty": 0,	 # 902
			"fill_time": None,	 # 908
			"fill_no": None,	 # 909
			"fill_price": 0,	 # 910
			"fill_qty": 0}		 # 911
		self.current_code = None
		self.search_result = None
		self.stop_loss_triggered = False
	async def connect(self):
		try:
			self.websocket = await websockets.connect(self.uri)
			# 아직 LOGIN 성공 전이므로 False 유지
			self.connected = False
			await self.send({"trnm": "LOGIN", "token": self.token})
		except Exception as e:
			log("★WEBSK_connect") #웹소켓 연결 실패
			print(e)
			self.connected = False
	async def send(self, message):
		if not isinstance(message, str):
			message = json.dumps(message)

		#print("SEND :", message)
		await self.websocket.send(message)
	async def receive(self):
		try:
			while True:
				response = json.loads(await self.websocket.recv())
				print(response)

				if response.get("trnm") == "LOGIN":
					if response.get("return_code") == 0:
						self.connected = True
						print("WEBSK") #웹소켓 로그인 성공
					else:
						if response.get("return_code") == 8005:
							print("Token expired -> Issuing new token")  # 토큰 만료 → 새 토큰 발급
							self.token = get_token()
						else:
							log("★WEBSK_receive")
							print(response)

						await self.disconnect()
						return

				elif response.get("trnm") == "PING":
					self.last_alive = time.time()
					await self.send(response)

				elif response.get("trnm") == "REAL":
					#print("수신:", response.get("trnm"))
					self.last_alive = time.time()
					self.handle_real(response)					

				elif response.get("trnm") == "CNSRLST":

					if response.get("return_code") != 0:
						log("★PGM") #조건검색 목록 조회 실패
						self.search_result = []
						continue

					await self.send({
						"trnm": "CNSRREQ",
						"seq": "0",
						"search_type": "0",
						"stex_tp": "K",
						"cont_yn": "N",
						"next_key": ""})
					
				elif response.get("trnm") == "CNSRREQ":
					data = response.get("data")
					if not data:
						self.search_result = []
						continue
					codes = []
					for item in data:
						codes.append(item["9001"].replace("A", ""))
					self.search_result = codes					
				elif response.get("trnm") == "REG":
					print("REG:", response)

		except websockets.ConnectionClosed:
			print("WebSocket connection closed")  # 웹소켓 연결 종료
			self.connected = False

		except Exception as e:
			print(f"WebSocket error: {e}")  # 웹소켓 오류
			self.connected = False
	async def run(self):
		while True:
			try:
				print("run connect")
				await self.connect()
				print("run receive")
				await self.receive()
			except Exception as e:
				print(f"Run loop error: {e}")  # run 오류

			self.connected = False
			await asyncio.sleep(5)
	async def disconnect(self):
		self.connected = False

		if self.websocket:
			await self.websocket.close()
			self.websocket = None
	async def register_price(self, code):
		code = code.replace("A", "")
		#print(code)
		self.current_code = code
		await self.send({
			"trnm":"REG",
			"grp_no":"1",
			"refresh":"1",
			"data":[{
				"item":[code],
				"type":["0B","0H"]}]})
	
	async def unregister_price(self, code):
		code = code.replace("A", "")
		await self.send({
			"trnm": "UNREG",
			"grp_no": "1",
			"data": [{
				"item": [code],
				"type": ["0B", "0H"]}]})
	
	async def register_order(self):
		await self.send({
			"trnm": "REG",
			"grp_no": "2",
			"refresh": "1",
			"data": [{
				"item": [""],
				"type": ["00"]}]})		# 주문체결
	async def reconnect(self):
		print("WEBSK reconnect start") #웹소켓 재연결 시작
		self.search_result = None 
		await self.disconnect()
		while True:
			try:
				await self.disconnect()
				await self.connect()
				asyncio.create_task(self.receive())
				break
			except Exception as e:
				print(f"Reconnection failed: {e}")  # 재연결 실패
				await asyncio.sleep(5)
		await self.register_order()
		if self.current_code:
			await self.register_price(self.current_code)
		print("WebSocket reconnection completed")  # 웹소켓 재연결 완료
	def handle_real(self, response):
		for item in response.get("data", []):
			real_type = item.get("type")
			values = item.get("values", {})

			if real_type == "0B":
				state = load_state()

				if not state["holding"]:
					continue
				self.price_data["current_price"] = abs(int(values.get("10") or 0))
				stop_price = int(state["buy_price"] * (1 - abs(STOP_LOSS_RATE)))
				if (
					self.price_data["current_price"] <= stop_price
					and not self.stop_loss_triggered):
					self.stop_loss_triggered = True

			elif real_type == "0H":
				self.price_data["expected_price"] = abs(int(values.get("10") or 0))

			elif real_type == "00":
				print("ORDER REAL:", values)
				order_no = values.get("9203")
				status = values.get("913")
				fill_price = abs(int(values.get("910") or 0))
				fill_qty = int(values.get("911") or 0)
				#print("주문체결 REAL 수신:", values)
				state = load_state()

				if (
					order_no == state["buy_order_no"]
					and status == "체결"):
					state["holding"] = True
					state["qty"] = fill_qty
					state["buy_price"] = fill_price
					buy_date = datetime.today()
					state["buy_date"] = buy_date.strftime("%Y%m%d")
					force_sell_date = get_force_sell_date(buy_date)
					state["force_sell_date"] = force_sell_date.strftime("%Y%m%d")
					state["buy_order_no"] = None
					save_state(state)
					log("B") #매수 체결 완료
				
				elif (
					order_no == state["sell_order_no"]
					and status == "체결"):
					remain_qty = int(values.get("902") or 0)
					if remain_qty == 0:
						self.stop_loss_triggered = False
						avg_price = int(values.get("914") or 0)
						clear_state()
						log(f"S_{avg_price}")

	async def search_condition(self):
		if not self.connected:
			return []
		self.search_result = None
		await self.send({"trnm":"CNSRLST"})
		for _ in range(100):
			if self.search_result is not None:
				return self.search_result
			await asyncio.sleep(0.1)
		return []