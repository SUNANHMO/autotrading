
import asyncio
import json
import time
import websockets

from datetime import datetime
from telegram_log import log
from b_auth import get_token
from e_state import load_state, save_state, clear_state
from a_config import WS_URL, STOP_LOSS_RATE

class WebSocketClient:
	def __init__(self, token):
		self.last_alive = time.time()
		self.uri = WS_URL
		self.token = token
		self.websocket = None
		self.connected = False
		self.running = True

		self.price_data = {
			"current_price": 0,
			"expected_price": 0,
			"opening_price": 0,
			"high_price": 0,}

		self.order_data = {
			"order_no": None,
			"status": None,
			"remain_qty": 0,
			"fill_time": None,
			"fill_no": None,
			"fill_price": 0,
			"fill_qty": 0,}

		self.current_code = None
		self.search_result = None
		self.stop_loss_triggered = False

		# 주문 이벤트의 중복 처리 방지
		self.processed_fill_ids = set()

		# 체결 처리 및 익절 주문 교체 직렬화
		self.order_lock = asyncio.Lock()

	# ------------------------------------------
	# WebSocket 연결
	# ------------------------------------------
	async def connect(self):
		try:
			self.websocket = await websockets.connect(self.uri)
			self.last_alive = time.time()
			self.connected = False
			await self.send({"trnm": "LOGIN", "token": self.token,})
		except Exception as e:
			log("★WEBSK_CONNECT")
			print("WebSocket 연결 오류:", e)
			self.connected = False

	async def send(self, message):
		if not self.websocket:
			raise ConnectionError("WebSocket 연결이 없습니다.")
		if not isinstance(message, str):
			message = json.dumps(message)
		await self.websocket.send(message)

	async def disconnect(self):
		self.connected = False
		if self.websocket:
			try:
				await self.websocket.close()
			except Exception:
				pass
			self.websocket = None

	async def stop(self):
		print("WebSocket stopping...")
		self.running = False
		await self.disconnect()

	async def reconnect(self):
		print("WebSocket reconnect requested")
		self.search_result = None
		await self.disconnect()

	# ------------------------------------------
	# 로그인 후 등록
	# ------------------------------------------

	async def register_price(self, code):
		code = str(code).replace("A", "")
		if not code:
			return
		self.current_code = code

		print(f"REGISTER PRICE START: {code}")

		await self.send({
			"trnm": "REG",
			"grp_no": "1",
			"refresh": "1",
			"data": [{
				"item": [code],
				"type": ["0B", "0H"],}],})

	async def register_prices(self, codes):
		"""
		보유 종목과 매수 후보 종목을 같은 등록 요청에 포함한다.
		그룹 등록을 교체하는 방식이므로 두 종목의 가격을 함께 감시할 수 있다.
		"""
		codes = list(dict.fromkeys(
			str(code).replace("A", "")
			for code in codes
			if code))

		if not codes:
			return

		self.current_code = codes[0]

		await self.send({
			"trnm": "REG",
			"grp_no": "1",
			"refresh": "1",
			"data": [{
				"item": codes,
				"type": ["0B", "0H"],}],})
		print("REGISTER PRICES:", codes)

	async def unregister_price(self, code):
		code = str(code).replace("A", "")
		await self.send({
			"trnm": "UNREG",
			"grp_no": "1",
			"data": [{
				"item": [code],
				"type": ["0B", "0H"],}],})

	async def register_order(self):
		await self.send({
			"trnm": "REG",
			"grp_no": "2",
			"refresh": "1",
			"data": [{
				"item": [""],
				"type": ["00"],	}],})

	# ------------------------------------------
	# 수신 루프
	# ------------------------------------------
	async def receive(self):
		try:
			while self.running:
				raw = await self.websocket.recv()
				response = json.loads(raw)

				trnm = response.get("trnm")

				if trnm == "LOGIN":
					if response.get("return_code") == 0:
						self.connected = True
						self.last_alive = time.time()
						print("WEBSK LOGIN SUCCESS")
						await self.register_order()
						state = load_state()
						codes = [
							state.get("code") if state.get("holding") else None,
							state.get("candidate_code"),]
						await self.register_prices(codes)

					elif response.get("return_code") in (805004, 8005):
						print("Token expired -> Issuing new token")
						new_token = get_token()
						if new_token:
							self.token = new_token
						else:
							log("★TOKEN_REFRESH_WS")
						await self.disconnect()
						return

					else:
						print("LOGIN FAIL:", response)
						log("★WEBSK_LOGIN")
						await self.disconnect()
						return

				elif trnm == "PING":
					self.last_alive = time.time()
					await self.send(response)

				elif trnm == "REAL":
					self.last_alive = time.time()
					self.handle_real(response)

				elif trnm == "CNSRLST":
					if response.get("return_code") != 0:
						log("★PGM")
						self.search_result = []
						continue

					await self.send({
						"trnm": "CNSRREQ",
						"seq": "1",
						"search_type": "0",
						"stex_tp": "K",
						"cont_yn": "N",
						"next_key": "",})

				elif trnm == "CNSRREQ":
					data = response.get("data") or []
					self.search_result = [
						item["9001"].replace("A", "")
						for item in data
						if item.get("9001")]

				elif trnm == "REG":
					print("REG:", response)

		except websockets.ConnectionClosed as e:
			print("WebSocket connection closed:", e)
			self.connected = False

		except Exception as e:
			import traceback
			print(f"WebSocket receive error: {type(e).__name__}: {e}")
			traceback.print_exc()
			log(f"★WEBSK_RECEIVE_{type(e).__name__}")
			self.connected = False

	async def run(self):
		while self.running:
			try:
				print("WebSocket connecting...")
				await self.connect()
				if self.websocket:
					await self.receive()
			except Exception as e:
				print("WebSocket run error:", e)
			self.connected = False
			if self.running:
				await asyncio.sleep(5)
		print("WebSocket run loop stopped")

	# ------------------------------------------
	# 실시간 이벤트 처리
	# ------------------------------------------
	def handle_real(self, response):
		for item in response.get("data", []):
			real_type = item.get("type")
			values = item.get("values") or {}

			# 종목 코드는 수신 형식에 따라 item 또는 다른 필드에 있을 수 있다.
			raw_code = item.get("item") or item.get("stk_cd")
			if isinstance(raw_code, list):
				raw_code = raw_code[0] if raw_code else None
			code = (
				str(raw_code).replace("A", "")
				if raw_code
				else self.current_code)
			if real_type == "0B":
				#print(
				#	f"[실시간 체결] "
				#	f"code={code}, "
				#	f"time={values.get('20')}, "
				#	f"현재가={values.get('10')}, "
				#	f"시가={values.get('16')}, "
				#	f"고가={values.get('17')}")
				self._handle_stock_price(code, values)
			
			elif real_type == "0H":
				price = self._to_int(values.get("10"))
				if price > 0 and code == self.current_code:
					self.price_data["expected_price"] = price

			elif real_type == "00":
				self._handle_order_event(values)

	@staticmethod
	def _to_int(value):
		try:
			return abs(int(value or 0))
		except (TypeError, ValueError):
			return 0

	def _handle_stock_price(self, code, values):
		if not code:
			return

		current_price = self._to_int(values.get("10"))
		opening_price = self._to_int(values.get("16"))
		high_price = self._to_int(values.get("17"))

		state = load_state()

		# 보유 종목의 실시간 가격 및 손절 감시
		if state.get("holding") and code == state.get("code"):
			if current_price > 0:
				self.price_data["current_price"] = current_price

			buy_price = self._to_int(state.get("buy_price"))
			qty = self._to_int(state.get("qty"))

			if (
				buy_price > 0
				and qty > 0
				and current_price > 0
				and not state.get("stop_loss_triggered", False)):
				stop_price = int(buy_price * (1 - abs(STOP_LOSS_RATE)))
				if current_price <= stop_price:
					state["stop_loss_triggered"] = True
					save_state(state)

					self.stop_loss_triggered = True
					log(f"STOP_{code}")

					# 실시간 콜백에서 비동기 주문을 직접 기다리지 않는다.
					asyncio.create_task(self._execute_stop_loss())

		# 미체결 매수 주문의 시초가 대비 고가 상승 추적
		if (state.get("buy_order_no") and code == state.get("candidate_code")):
			if opening_price > 0 and not state.get("opening_price"):
				state["opening_price"] = opening_price

			if high_price > 0:
				self.price_data["high_price"] = max(self.price_data["high_price"], high_price,)
			official_open = self._to_int(state.get("opening_price"))
			observed_high = max(high_price, self.price_data["high_price"],)

			if (official_open > 0 and observed_high >= official_open * 1.05 and not state.get("opening_high_cancelled", False)):
				# 중복 취소 요청을 막기 위해 우선 플래그를 기록한다.
				state["opening_high_cancelled"] = True
				save_state(state)
				asyncio.create_task(self._cancel_unfilled_buy())

	async def _cancel_unfilled_buy(self):
		from f_order import cancel_buy_order
		try:
			result = await asyncio.to_thread(cancel_buy_order, self.token,)
			if result:
				log("BUY_REMAINDER_CANCEL_REQUESTED")
			else:
				log("★BUY_REMAINDER_CANCEL_CHECK")
		except Exception as e:
			log(f"★BUY_REMAINDER_CANCEL_{type(e).__name__}")
			print("매수 잔량 취소 오류:", e)

	# ------------------------------------------
	# 주문 체결 이벤트
	# ------------------------------------------
	def _handle_order_event(self, values):
		order_no = values.get("9203")
		status = values.get("913")
		fill_price = self._to_int(values.get("910"))
		fill_qty = self._to_int(values.get("911"))
		remain_qty = self._to_int(values.get("902"))
		fill_no = values.get("909")

		self.order_data.update({
			"order_no": order_no,
			"status": status,
			"remain_qty": remain_qty,
			"fill_time": values.get("908"),
			"fill_no": fill_no,
			"fill_price": fill_price,
			"fill_qty": fill_qty,})
		print("ORDER REAL:", values)
		state = load_state()

		# 체결 완료 이벤트가 아닌 단순 접수/확인 이벤트는 체결 수량으로 반영하지 않는다.
		if status != "체결" or fill_qty <= 0 or fill_price <= 0:
			return
		# 동일 체결 이벤트의 중복 반영 방지.
		# fill_no가 제공되지 않으면 중복 방지를 보장할 수 없다.
		if fill_no:
			fill_id = f"{order_no}:{fill_no}"
			if fill_id in self.processed_fill_ids:
				return
			self.processed_fill_ids.add(fill_id)

			# 메모리 사용량 제한
			if len(self.processed_fill_ids) > 5000:
				self.processed_fill_ids.clear()

		if order_no == state.get("buy_order_no"):
			asyncio.create_task(
				self._process_buy_fill(order_no, fill_price, fill_qty, remain_qty,))

		elif order_no == state.get("sell_order_no"):
			asyncio.create_task(
				self._process_sell_fill(order_no, fill_price, fill_qty, remain_qty,))
		elif order_no == state.get("take_profit_order_no"):
			asyncio.create_task(
				self._process_take_profit_fill(order_no, fill_price, fill_qty, remain_qty,))

	async def _process_buy_fill(self, order_no, fill_price, fill_qty, remain_qty,):
		from f_order import cancel_take_profit, take_profit_krx
		async with self.order_lock:
			state = load_state()
			if order_no != state.get("buy_order_no"):
				return
			old_qty = self._to_int(state.get("qty"))
			old_price = self._to_int(state.get("buy_price"))
			new_qty = old_qty + fill_qty
			if new_qty <= 0:
				return
			# 누적 체결 가격 기준 가중평균
			state["buy_price"] = (
				(old_qty * old_price) + (fill_qty * fill_price)
			) // new_qty

			state["qty"] = new_qty
			state["holding"] = True
			state["buy_date"] = datetime.today().strftime("%Y%m%d")
			state["position_origin"] = "new"
			state["buy_remaining_qty"] = remain_qty
			state["buy_filled_qty"] = (
				self._to_int(state.get("buy_filled_qty"))
				+ fill_qty)
			if remain_qty == 0:
				state["buy_order_no"] = None
			save_state(state)
			log(f"BUY_FILL_{fill_qty}_{fill_price}")

			# 체결된 주식이 생기면 손절 감시를 활성화한다.
			self.stop_loss_triggered = False

			# 추가 부분 체결 시 기존 익절 주문을 취소하고
			# 전체 보유 수량에 맞춰 다시 제출한다.
			if state.get("take_profit_order_no"):
				cancel_no = await asyncio.to_thread(cancel_take_profit, self.token,)
				if not cancel_no:
					log("★TP_REPLACE_CANCEL")
					return
			tp_no = await asyncio.to_thread(take_profit_krx, self.token,)
			if not tp_no:
				log("★TP_AFTER_BUY_FILL")

	async def _process_take_profit_fill(
		self,
		order_no,
		fill_price,
		fill_qty,
		remain_qty,
	):
		async with self.order_lock:
			state = load_state()

			if order_no != state.get("take_profit_order_no"):
				return

			qty = max(
				0,
				self._to_int(state.get("qty")) - fill_qty,
			)

			state["qty"] = qty

			if qty == 0:
				clear_state()
				self.stop_loss_triggered = False
				log(f"TP_FILLED_{fill_price}")
			else:
				# 부분 매도 후에는 실제 계좌 수량을 다시 조회해야 한다.
				state["take_profit_order_no"] = (
					order_no if remain_qty > 0 else None
				)
				save_state(state)
				log(f"TP_PARTIAL_{qty}")

	async def _process_sell_fill(self, order_no, fill_price, fill_qty, remain_qty,):
		async with self.order_lock:
			state = load_state()
			if order_no != state.get("sell_order_no"):
				return
			qty = max(0, self._to_int(state.get("qty")) - fill_qty,)
			if qty == 0:
				clear_state()
				self.stop_loss_triggered = False
				log(f"SELL_FILLED_{fill_price}")
			else:
				state["qty"] = qty
				save_state(state)
				log(f"SELL_PARTIAL_{qty}")

	async def _execute_stop_loss(self):
		from f_order import market_sell

		async with self.order_lock:
			state = load_state()

			if (
				not state.get("holding")
				or self._to_int(state.get("qty")) <= 0
				or state.get("sell_order_no")):
				return
			try:
				order_no = await asyncio.to_thread(market_sell, self.token,)
				if order_no:
					log(f"STOP_SELL_{order_no}")
				else:
					log("★STOP_SELL_ORDER")

			except Exception as e:
				log(f"★STOP_SELL_{type(e).__name__}")
				print("손절 시장가 매도 오류:", e)

	# ------------------------------------------
	# 조건 검색
	# ------------------------------------------
	async def search_condition(self):
		if not self.connected:
			return []
		self.search_result = None
		await self.send({"trnm": "CNSRLST",})
		for _ in range(100):
			if self.search_result is not None:
				return self.search_result
			await asyncio.sleep(0.1)
		log("★PGM_TIMEOUT")
		return []
