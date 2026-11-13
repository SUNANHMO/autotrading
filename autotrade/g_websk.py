
import asyncio
import json
import time
import os
import websockets

from datetime import datetime
from telegram_log import log
from b_auth import get_token
from e_state import load_state, save_state, clear_state
from etf_state import (load_state as load_etf_state, save_state as save_etf_state,)
from etf_order_manager import record_fill as record_etf_fill
from a_config import WS_URL, STOP_LOSS_RATE


ETF_CODES = ("069500", "114800")


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
			"high_price": 0,
		}

		self.order_data = {
			"order_no": None,
			"status": None,
			"remain_qty": 0,
			"fill_time": None,
			"fill_no": None,
			"fill_price": 0,
			"fill_qty": 0,
		}

		self.current_code = None
		self.search_result = None
		self.stop_loss_triggered = False

		self.processed_fill_ids = set()
		self.order_lock = asyncio.Lock()

		# ETF 종목별 실시간 호가 저장
		self.etf_quote_data = {
			code: {
				"current_price": 0,
				"best_bid": 0,
				"best_ask": 0,
				"market_time": None,
				"received_at": None,
			}
			for code in ETF_CODES
		}

		# 삼성전자 프로그램 순매수 실시간 기록
		self.program_flow_file = "program_flow_live.json"
		self.program_flow_data = self._load_program_flow_data()

	# ------------------------------------------
	# WebSocket 연결
	# ------------------------------------------

	async def connect(self):
		try:
			self.websocket = await websockets.connect(self.uri)
			self.last_alive = time.time()
			self.connected = False

			await self.send({
				"trnm": "LOGIN",
				"token": self.token,
			})

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
	# 실시간 등록
	# ------------------------------------------

	async def register_price(self, code):
		await self.register_prices([code])

	async def register_prices(self, codes):
		"""
		선도주 및 후보 종목과 ETF 두 종목을
		하나의 그룹으로 등록한다.
		"""

		state = load_state()

		all_codes = list(codes or [])

		if state.get("holding") and state.get("code"):
			all_codes.append(state["code"])

		if state.get("candidate_code"):
			all_codes.append(state["candidate_code"])

		# ETF 시세는 항상 함께 등록
		all_codes.extend(ETF_CODES)

		all_codes = list(dict.fromkeys(
			str(code).replace("A", "")
			for code in all_codes
			if code
		))

		if not all_codes:
			return

		stock_codes = [
			code for code in all_codes
			if code not in ETF_CODES
		]

		if stock_codes:
			self.current_code = stock_codes[0]

		await self.send({
			"trnm": "REG",
			"grp_no": "1",
			"refresh": "1",
			"data": [{
				"item": all_codes,
				"type": ["0B", "0H"],
			}],
		})

		print("REGISTER PRICES:", all_codes)

	async def unregister_price(self, code):
		code = str(code).replace("A", "")

		# ETF는 상시 감시하므로 해제하지 않는다.
		if code in ETF_CODES:
			return

		await self.send({
			"trnm": "UNREG",
			"grp_no": "1",
			"data": [{
				"item": [code],
				"type": ["0B", "0H"],
			}],
		})

	async def register_order(self):
		await self.send({
			"trnm": "REG",
			"grp_no": "2",
			"refresh": "1",
			"data": [{
				"item": [""],
				"type": ["00"],
			}],
		})

	async def register_program_flow(self):
		await self.send({
			"trnm": "REG",
			"grp_no": "3",
			"refresh": "1",
			"data": [{
				"item": ["005930"],
				"type": ["0w"],
			}],
		})

		print("REGISTER PROGRAM FLOW: 005930")

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
							state.get("candidate_code"),
						]

						await self.register_prices(codes)
						await self.register_program_flow()

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
						"next_key": "",
					})

				elif trnm == "CNSRREQ":
					data = response.get("data") or []

					self.search_result = [
						item["9001"].replace("A", "")
						for item in data
						if item.get("9001")
					]

				elif trnm == "REG":
					print("REG:", response)

		except websockets.ConnectionClosed as e:
			print("WebSocket connection closed:", e)
			self.connected = False

		except Exception as e:
			import traceback

			print(
				f"WebSocket receive error: "
				f"{type(e).__name__}: {e}"
			)

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

			raw_code = item.get("item") or item.get("stk_cd")

			if isinstance(raw_code, list):
				raw_code = raw_code[0] if raw_code else None

			code = (
				str(raw_code).replace("A", "")
				if raw_code
				else None
			)

			if real_type == "0B":
				if not code:
					continue

				#print(
				#	f"[실시간 체결] "
				#	f"code={code}, "
				#	f"time={values.get('20')}, "
				#	f"현재가={values.get('10')}, "
				#	f"시가={values.get('16')}, "
				#	f"고가={values.get('17')}"
				#)

				# ETF 호가 저장
				if code in ETF_CODES:
					self._handle_etf_quote(code, values)

				# 기존 선도주 처리 유지
				self._handle_stock_price(code, values)

			elif real_type == "0H":
				if not code:
					continue

				price = self._to_int(values.get("10"))

				if price > 0 and code == self.current_code:
					self.price_data["expected_price"] = price

			elif real_type == "00":
				self._handle_order_event(values)

			elif real_type == "0w":
				self._record_program_flow(values)

				#print(
				#	"[프로그램 수급 수신]",
				#	f"code={code or '005930'}",
				#	f"time={values.get('20')}",
				#	f"net_amount={values.get('212')}",
				#)

	# ------------------------------------------
	# ETF 호가 관리
	# ------------------------------------------

	def _handle_etf_quote(self, code, values):
		"""
		0B 실시간 데이터
		FID 10: 현재가
		FID 27: 최우선 매도호가
		FID 28: 최우선 매수호가
		"""

		current_price = self._to_int(values.get("10"))
		best_ask = self._to_int(values.get("27"))
		best_bid = self._to_int(values.get("28"))

		if current_price <= 0 or best_bid <= 0 or best_ask <= 0:
			return

		quote = self.etf_quote_data[code]

		quote["current_price"] = current_price
		quote["best_bid"] = best_bid
		quote["best_ask"] = best_ask
		quote["market_time"] = values.get("20")
		quote["received_at"] = time.time()

		#print(
		#	f"[ETF 호가 수신] code={code}, "
		#	f"현재가={current_price:,}, "
		#	f"매수호가={best_bid:,}, "
		#	f"매도호가={best_ask:,}"
		#)

	def get_etf_quote(self, code, max_age_seconds=3):
		"""
		최신 ETF 호가 반환.
		마지막 수신 이후 지정된 시간이 지나면 None 반환.
		"""

		code = str(code).replace("A", "")

		if code not in ETF_CODES:
			return None

		quote = self.etf_quote_data.get(code)

		if not quote:
			return None

		received_at = quote.get("received_at")

		if received_at is None:
			return None

		if time.time() - received_at > max_age_seconds:
			return None

		if (
			quote["best_bid"] <= 0
			or quote["best_ask"] <= 0
		):
			return None

		return dict(quote)

	# ------------------------------------------
	# 프로그램 수급 기록
	# ------------------------------------------

	def _load_program_flow_data(self):
		today = datetime.now().strftime("%Y%m%d")

		try:
			with open(
				self.program_flow_file,
				"r",
				encoding="utf-8",
			) as f:
				data = json.load(f)

			if data.get("date") == today:
				return data

		except (
			FileNotFoundError,
			json.JSONDecodeError,
			OSError,
		):
			pass

		return {
			"date": today,
			"stock_code": "005930",
			"unit": "백만원",
			"current_net_amount": None,
			"current_time": None,
			"high_net_amount": None,
			"high_time": None,
			"low_net_amount": None,
			"low_time": None,
		}

	def _record_program_flow(self, values):
		raw_amount = values.get("212")

		if raw_amount is None:
			return

		try:
			# 부호를 보존해야 하므로 abs()를 사용하지 않는다.
			amount = int(
				str(raw_amount)
				.strip()
				.replace(",", "")
				.replace("+", "")
			)

		except (TypeError, ValueError):
			print("프로그램 수급 금액 파싱 실패:", raw_amount)
			return

		today = datetime.now().strftime("%Y%m%d")

		if self.program_flow_data.get("date") != today:
			self.program_flow_data = self._load_program_flow_data()

		event_time = str(
			values.get("20")
			or datetime.now().strftime("%H%M%S")
		)

		data = self.program_flow_data

		data["current_net_amount"] = amount
		data["current_time"] = event_time

		if (
			data.get("high_net_amount") is None
			or amount > data["high_net_amount"]
		):
			data["high_net_amount"] = amount
			data["high_time"] = event_time

		if (
			data.get("low_net_amount") is None
			or amount < data["low_net_amount"]
		):
			data["low_net_amount"] = amount
			data["low_time"] = event_time

		temp_file = self.program_flow_file + ".tmp"

		try:
			with open(temp_file, "w", encoding="utf-8") as f:
				json.dump(data, f, ensure_ascii=False, indent=2)

			os.replace(temp_file, self.program_flow_file)

		except OSError as e:
			log("★PROGRAM_FLOW_SAVE")
			print("프로그램 수급 파일 저장 오류:", e)

	@staticmethod
	def _to_int(value):
		try:
			return abs(int(value or 0))
		except (TypeError, ValueError):
			return 0

	# ------------------------------------------
	# 기존 선도주 가격 처리
	# ------------------------------------------

	def _handle_stock_price(self, code, values):
		if not code:
			return

		current_price = self._to_int(values.get("10"))
		opening_price = self._to_int(values.get("16"))
		high_price = self._to_int(values.get("17"))

		state = load_state()

		if state.get("holding") and code == state.get("code"):
			if current_price > 0:
				self.price_data["current_price"] = current_price

			buy_price = self._to_int(state.get("buy_price"))
			qty = self._to_int(state.get("qty"))

			if (
				buy_price > 0
				and qty > 0
				and current_price > 0
				and not state.get("stop_loss_triggered", False)
			):
				stop_price = int(
					buy_price * (1 - abs(STOP_LOSS_RATE))
				)

				if current_price <= stop_price:
					state["stop_loss_triggered"] = True
					save_state(state)

					self.stop_loss_triggered = True
					log(f"STOP_{code}")

					asyncio.create_task(
						self._execute_stop_loss()
					)

		if (
			state.get("buy_order_no")
			and code == state.get("candidate_code")
		):
			if opening_price > 0 and not state.get("opening_price"):
				state["opening_price"] = opening_price

			if high_price > 0:
				self.price_data["high_price"] = max(
					self.price_data["high_price"],
					high_price,
				)

			official_open = self._to_int(
				state.get("opening_price")
			)

			observed_high = max(
				high_price,
				self.price_data["high_price"],
			)

			if (
				official_open > 0
				and observed_high >= official_open * 1.05
				and not state.get("opening_high_cancelled", False)
			):
				state["opening_high_cancelled"] = True
				save_state(state)

				asyncio.create_task(
					self._cancel_unfilled_buy()
				)

	async def _cancel_unfilled_buy(self):
		from f_order import cancel_buy_order

		try:
			result = await asyncio.to_thread(
				cancel_buy_order,
				self.token,
			)

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
			"fill_qty": fill_qty,
		})

		print("ORDER REAL:", values)

		# --------------------------------------
		# ETF 취소 완료 이벤트 확인
		# --------------------------------------
		etf_code = str(
			values.get("9001") or ""
		).replace("A", "")
	
		original_order_no = str(
			values.get("904") or ""
		).strip()
	
		order_type = str(values.get("905") or "")
	
		if (
			etf_code in ETF_CODES
			and "취소" in order_type
			and status in ("확인", "취소")
		):
			cancel_state = load_etf_state()
	
			requested_order_no = str(
				cancel_state.get("cancel_requested_order_no") or ""
			)
	
			if (
				requested_order_no
				and original_order_no == requested_order_no
			):
				cancel_state["cancel_confirmed_order_no"] = (
					original_order_no
				)
	
				cancel_state["cancel_confirmed_time"] = (
					datetime.now().strftime("%H%M%S")
				)
	
				save_etf_state(cancel_state)
	
				print(
					"[ETF 취소 완료 확인] "
					f"code={etf_code}, "
					f"original_order_no={original_order_no}"
				)
	
				log(f"ETF_CANCEL_CONFIRMED_{original_order_no}")
				return
		
		# ETF 주문인지 먼저 확인
		etf_state = load_etf_state()

		if (
			order_no
			and etf_state.get("order_no")
			and str(order_no) == str(etf_state["order_no"])
		):
			if status != "체결" or fill_qty <= 0 or fill_price <= 0:
				return

			if not fill_no:
				log("★ETF_FILL_ID_MISSING")
				print(
					"ETF 체결번호가 없어 중복 방지를 위해 "
					"반영하지 않았습니다."
				)
				return

			asyncio.create_task(
				self._process_etf_fill(
					order_no,
					fill_qty,
					fill_no,
				)
			)

			return

		# --------------------------------------
		# 아래부터 기존 선도주 주문 처리
		# --------------------------------------

		state = load_state()

		if (
			status != "체결"
			or fill_qty <= 0
			or fill_price <= 0
		):
			return

		if fill_no:
			fill_id = f"{order_no}:{fill_no}"

			if fill_id in self.processed_fill_ids:
				return

			self.processed_fill_ids.add(fill_id)

			if len(self.processed_fill_ids) > 5000:
				self.processed_fill_ids.clear()

		if order_no == state.get("buy_order_no"):
			asyncio.create_task(
				self._process_buy_fill(
					order_no,
					fill_price,
					fill_qty,
					remain_qty,
				)
			)

		elif order_no == state.get("sell_order_no"):
			asyncio.create_task(
				self._process_sell_fill(
					order_no,
					fill_price,
					fill_qty,
					remain_qty,
				)
			)

		elif order_no == state.get("take_profit_order_no"):
			asyncio.create_task(
				self._process_take_profit_fill(
					order_no,
					fill_price,
					fill_qty,
					remain_qty,
				)
			)

	async def _process_etf_fill(
		self,
		order_no,
		fill_qty,
		fill_no,
	):
		"""
		ETF 체결은 별도 상태 파일과 주문 관리 함수로 처리한다.
		기존 선도주 상태에는 접근하지 않는다.
		"""

		async with self.order_lock:
			try:
				result = record_etf_fill(
					order_no,
					fill_qty,
					fill_no,
				)

				print(
					f"[ETF 체결 반영] "
					f"order_no={order_no}, "
					f"fill_qty={fill_qty}, "
					f"fill_no={fill_no}, "
					f"result={result}"
				)

				log(f"ETF_FILL_{result}")

			except Exception as e:
				log(f"★ETF_FILL_{type(e).__name__}")
				print("ETF 체결 처리 오류:", e)

	# ------------------------------------------
	# 기존 선도주 매수 체결
	# ------------------------------------------

	async def _process_buy_fill(
		self,
		order_no,
		fill_price,
		fill_qty,
		remain_qty,
	):
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
				+ fill_qty
			)

			if remain_qty == 0:
				state["buy_order_no"] = None

			save_state(state)

			log(f"BUY_FILL_{fill_qty}_{fill_price}")

			self.stop_loss_triggered = False

			if state.get("take_profit_order_no"):
				cancel_no = await asyncio.to_thread(
					cancel_take_profit,
					self.token,
				)

				if not cancel_no:
					log("★TP_REPLACE_CANCEL")
					return

			tp_no = await asyncio.to_thread(
				take_profit_krx,
				self.token,
			)

			if not tp_no:
				log("★TP_AFTER_BUY_FILL")

	# ------------------------------------------
	# 기존 선도주 익절 체결
	# ------------------------------------------

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
				state["take_profit_order_no"] = (
					order_no if remain_qty > 0 else None
				)

				save_state(state)
				log(f"TP_PARTIAL_{qty}")

	# ------------------------------------------
	# 기존 선도주 매도 체결
	# ------------------------------------------

	async def _process_sell_fill(
		self,
		order_no,
		fill_price,
		fill_qty,
		remain_qty,
	):
		async with self.order_lock:
			state = load_state()

			if order_no != state.get("sell_order_no"):
				return

			qty = max(
				0,
				self._to_int(state.get("qty")) - fill_qty,
			)

			if qty == 0:
				clear_state()
				self.stop_loss_triggered = False
				log(f"SELL_FILLED_{fill_price}")

			else:
				state["qty"] = qty
				save_state(state)
				log(f"SELL_PARTIAL_{qty}")

	# ------------------------------------------
	# 기존 선도주 손절
	# ------------------------------------------

	async def _execute_stop_loss(self):
		from f_order import market_sell

		async with self.order_lock:
			state = load_state()

			if (
				not state.get("holding")
				or self._to_int(state.get("qty")) <= 0
				or state.get("sell_order_no")
			):
				return

			try:
				order_no = await asyncio.to_thread(
					market_sell,
					self.token,
				)

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

		await self.send({
			"trnm": "CNSRLST",
		})

		for _ in range(100):
			if self.search_result is not None:
				return self.search_result

			await asyncio.sleep(0.1)

		log("★PGM_TIMEOUT")
		return []
