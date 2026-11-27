"""200억 프로그램 순매수 역전 ETF 전략 연결. 주문은 etf_execution이 단독 관리."""
import asyncio
import json
import os
import time
from datetime import datetime

from a_config import ETF_DC20_ENABLED
from etf_execution import reconcile_etf
from etf_state import load_state, save_state
from etf_strategy import replay_virtual_history, update_virtual_position
from telegram_log import log


class EtfLiveScheduler:
    def __init__(self):
        self.reset_day()

    def reset_day(self):
        self.ready = False
        self.mode_change_blocked = False
        self.last_order_check = 0.0
        self.last_close_check = 0.0
        self.last_logged_status = None
        self.last_quote_wait_logged = None

    def initialize(self, rows, now):
        # 과거 이력의 실제 마지막 시각까지 재생해 신호 기준점을 복원한다.
        cutoff = now.strftime("%H%M%S")
        before = load_state()
        pos, count, last_time, net = replay_virtual_history(
            rows, trading_date=now.strftime("%Y%m%d"), cutoff_time=cutoff)
        state = load_state()
        old_mode = state.get("execution_dc20_enabled")
        same_day = before.get("date") == now.strftime("%Y%m%d")
        if same_day and old_mode != ETF_DC20_ENABLED and (old_mode is not None or not ETF_DC20_ENABLED):
            self.mode_change_blocked = True
            print("[ETF] 장중 전략 변경 감지: 신규 장중 주문 차단, 마감 청산 유지")
        if not self.mode_change_blocked and (old_mode != ETF_DC20_ENABLED or (not ETF_DC20_ENABLED and not same_day)):
            # 기존 DC20 신호 가격을 최초 진입 주문에 재사용하지 않는다.
            # 모드 변경은 장 시작 전 잔고/미체결이 없는 상태에서만 수행해야 한다.
            if old_mode is not None or not ETF_DC20_ENABLED:
                state.update(signal_target=None, signal_prices={},
                             signal_initial_entry=False, pending_quote_target=None,
                             pending_quote_required=None)
            state["execution_dc20_enabled"] = ETF_DC20_ENABLED
            save_state(state)
        self.ready = True
        print(f"[ETF 가상 방향 복원] {pos}, {count}건, 마지막={last_time}, 순매수={net}")
        # 과거 신호에 대한 호가가 없으므로 과거 신호로 소급 주문하지 않는다.

    @staticmethod
    def _execution_target(state):
        return state.get("virtual_position" if ETF_DC20_ENABLED else "first_position", "NONE")

    @staticmethod
    def _flow(now):
        try:
            with open(os.path.join(os.path.dirname(__file__), "program_flow_live.json"), encoding="utf-8") as f:
                data = json.load(f)
            if data.get("date") != now.strftime("%Y%m%d") or data.get("stock_code") != "005930" or data.get("unit") != "백만원":
                return None
            tm = str(data.get("current_time") or "")
            if len(tm) != 6 or not tm.isdigit():
                return None
            dt = datetime.strptime(now.strftime("%Y%m%d") + tm, "%Y%m%d%H%M%S")
            age = (now - dt).total_seconds()
            if not 0 <= age <= 30:
                return None
            return tm, int(data["current_net_amount"])
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    @staticmethod
    def _capture_quotes(websocket, required=("KODEX200", "INVERSE")):
        if websocket is None or not getattr(websocket, "connected", False):
            return None
        prices = {}
        for target, code in (("KODEX200", "069500"), ("INVERSE", "114800")):
            if target not in required:
                continue
            q = websocket.get_etf_quote(code, max_age_seconds=3)
            if not q:
                return None
            bid = int(q.get("best_bid") or 0)
            ask = int(q.get("best_ask") or 0)
            if bid <= 0 or ask <= 0:
                return None
            prices[target] = {"bid": bid, "ask": ask}
        return prices

    async def tick(self, token, websocket, now):
        if not self.ready:
            return
        flow = self._flow(now)
        if flow:
            tm, net = flow
            state = load_state()
            if state.get("date") == now.strftime("%Y%m%d") and tm > str(state.get("last_flow_time") or ""):
                previous = state.get("virtual_position", "NONE")
                target = update_virtual_position(net, trading_date=now.strftime("%Y%m%d"))
                state = load_state()
                state["last_flow_time"] = tm
                if target != previous:
                    required = (target,) if previous == "NONE" else ("KODEX200", "INVERSE")
                    quotes = self._capture_quotes(websocket, required)
                    # 신호 시점 호가가 없으면 최신 방향에 한해 호가 수신을 기다린다.
                    # 가격 확보 후에는 최초 확보 가격으로 고정하고 추격하지 않는다.
                    if ETF_DC20_ENABLED or previous == "NONE":
                        state["signal_target"] = target if quotes else None
                        state["signal_prices"] = quotes or {}
                        state["signal_initial_entry"] = previous == "NONE"
                        state["pending_quote_required"] = list(required) if not quotes else None
                        state["pending_quote_target"] = target if (not quotes and target in ("KODEX200", "INVERSE")) else None
                    # 전환 전 ETF의 매도 1호가 / 전환 후 ETF의 매수 1호가를 알린다.
                    symbols = {"KODEX200": "U", "INVERSE": "D", "NONE": "N"}
                    direction = f"{symbols.get(previous, previous)}>{symbols.get(target, target)}"
                    clock = f"{tm[:2]}:{tm[2:4]}:{tm[4:6]}"
                    parts = [clock, direction]
                    if quotes:
                        if previous in ("KODEX200", "INVERSE"):
                            parts.append(f"{symbols[previous]}_{quotes[previous]['ask']:,}")
                        if target in ("KODEX200", "INVERSE"):
                            parts.append(f"{symbols[target]}_{quotes[target]['bid']:,}")
                    else:
                        parts.append("호가없음")
                    log(" / ".join(parts))
                    print(f"[ETF 전환 신호] {previous} -> {target}, {tm}, {net}, 호가={'확보' if quotes else '없음'}")
                save_state(state)

        # 새 수급 이벤트가 없어도 대기 중인 신호의 웹소켓 호가를 확인한다.
        # 다음 반전이 발생하면 위에서 pending_quote_target을 최신 방향으로 교체한다.
        state = load_state()
        pending = state.get("pending_quote_target")
        if pending in ("KODEX200", "INVERSE"):
            if self._execution_target(state) != pending:
                state["pending_quote_target"] = None
                state["pending_quote_required"] = None
                save_state(state)
            elif state.get("signal_target") != pending:
                required = state.get("pending_quote_required") or ("KODEX200", "INVERSE")
                quotes = self._capture_quotes(websocket, required)
                if quotes:
                    state["signal_target"] = pending
                    state["signal_prices"] = quotes
                    state["pending_quote_target"] = None
                    state["pending_quote_required"] = None
                    save_state(state)
                    print(f"[ETF 지연 호가 확보] {pending}, 매수호가={quotes[pending]['bid']}, 주문 재개")

        if self.mode_change_blocked:
            return

        # 주문 진행 상태는 수급 이벤트가 없어도 계좌/미체결 조회로 갱신한다.
        if time.monotonic() - self.last_order_check < 2.0:
            return
        self.last_order_check = time.monotonic()
        state = load_state()
        target = self._execution_target(state)
        if not ETF_DC20_ENABLED and state.get("active_stage") and state.get("active_target") != target:
            print("[ETF] 기존 주문 계획과 최초 방향 불일치: 장중 주문 보류")
            return
        try:
            status = await asyncio.to_thread(reconcile_etf, token, websocket, target)
            if status != self.last_logged_status:
                print(f"[ETF 주문 상태] {status}")
                self.last_logged_status = status
            if status in ("BUY_SUBMITTED", "SELL_SUBMITTED", "BUY_FAILED", "SELL_FAILED"):
                print(f"ETF_{status}")
        except json.JSONDecodeError as exc:
            # 응답 파싱 실패 시 이번 조회를 중단하고 다음 주기에 계좌/미체결을 재확인한다.
            # 일시적인 JSON 오류는 콘솔에만 기록한다.
            print(f"[ETF 주문 처리 JSON 오류 / 재조회 대기] {exc}")
        except Exception as exc:
            print(f"[ETF 주문 처리 오류] {exc}")
            log(f"★ETF_RECONCILE_{type(exc).__name__}")

    async def close(self, token, websocket):
        if time.monotonic() - self.last_close_check < 2.0:
            return
        self.last_close_check = time.monotonic()
        try:
            status = await asyncio.to_thread(reconcile_etf, token, websocket, "NONE", closing=True)
            if status != self.last_logged_status:
                print(f"[ETF 15:20 청산] {status}")
                self.last_logged_status = status
            if status in ("CLOSING_SELL_SUBMITTED", "CLOSING_SELL_FAILED", "CANCEL_REQUESTED"):
                print(f"ETF_{status}")
        except Exception as exc:
            print(f"[ETF 청산 처리 오류] {exc}")
            log(f"★ETF_CLOSING_{type(exc).__name__}")
