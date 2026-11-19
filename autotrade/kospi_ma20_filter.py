"""키움 ka20006 KOSPI 종합지수 전일 20일선 신규매수 게이트."""
import json
import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from a_config import REST_HOST
from telegram_log import log

STATE_PATH = Path(__file__).resolve().with_name("kospi_ma20_gate.json")


def _positive_index(value):
    # 지수는 100배 정수로 전달됨. 비교 시 나누지 않아도 비율은 동일.
    raw = str(value).strip().replace(",", "")
    if not raw or not raw.lstrip("+").isdigit():
        raise ValueError(f"지수 종가 형식 오류: {value!r}")
    number = int(raw)
    if number <= 0:
        raise ValueError("지수 종가가 0 이하")
    return number


def _fetch_previous_closes(token, trading_day):
    # 당일 일봉(진행 중)을 처음부터 조회하지 않도록 기준일을 전일로 지정.
    cutoff = trading_day.strftime("%Y%m%d")
    base_dt = (trading_day - timedelta(days=1)).strftime("%Y%m%d")
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "api-id": "ka20006", "cont-yn": "N", "next-key": "",
    }
    closes = {}
    seen_keys = set()
    for _ in range(5):
        response = requests.post(
            f"{REST_HOST}/api/dostk/chart",
            headers=headers,
            json={"inds_cd": "001", "base_dt": base_dt},
            timeout=15,
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or str(body.get("return_code")) != "0":
            raise ValueError(f"ka20006 응답 오류: {body}")
        if str(body.get("inds_cd", "001")) != "001":
            raise ValueError("KOSPI 업종코드 불일치")
        rows = body.get("inds_dt_pole_qry")
        if not isinstance(rows, list):
            raise ValueError("ka20006 일봉 목록 누락")
        for row in rows:
            day = str(row.get("dt", ""))
            datetime.strptime(day, "%Y%m%d")
            if day >= cutoff:
                continue
            close = _positive_index(row.get("cur_prc"))
            if day in closes and closes[day] != close:
                raise ValueError(f"중복 날짜 종가 불일치: {day}")
            closes[day] = close
        if len(closes) >= 20:
            break
        cont = response.headers.get("cont-yn", "N").strip().upper()
        key = response.headers.get("next-key", "").strip()
        if cont != "Y" or not key or key in seen_keys:
            break
        seen_keys.add(key)
        headers["cont-yn"], headers["next-key"] = "Y", key
    days = sorted(closes, reverse=True)
    if len(days) < 20:
        raise ValueError(f"전일 이전 일봉 부족: {len(days)}개")
    # 연휴/휴장 포함 7일 넘게 최신 일봉이 없으면 오래된 데이터로 차단.
    if (trading_day - datetime.strptime(days[0], "%Y%m%d").date()).days > 7:
        raise ValueError(f"최근 일봉 오래됨: {days[0]}")
    return [(day, closes[day]) for day in days[:20]]


def refresh_kospi_ma20_gate(token, trading_day=None):
    trading_day = trading_day or date.today()
    record = {"trading_day": trading_day.strftime("%Y%m%d"), "allowed": False}
    try:
        rows = _fetch_previous_closes(token, trading_day)
        yesterday_close = rows[0][1]
        ma20 = sum(close for _, close in rows) / 20
        record.update({
            "allowed": yesterday_close > ma20,
            "last_date": rows[0][0],
            "last_close": yesterday_close / 100,
            "ma20": ma20 / 100,
            "count": len(rows),
        })
        print(f"[KOSPI MA20] {rows[0][0]} 종가={yesterday_close / 100:.2f}, "
              f"MA20={ma20 / 100:.2f}, "
              f"주도주매수={'허용' if record['allowed'] else '차단'}")
        log("LEAD_MA20_ALLOW" if record["allowed"] else "LEAD_MA20_BLOCK")
    except Exception as exc:
        record["error"] = str(exc)
        print(f"[KOSPI MA20] 조회/검증 실패, 주도주 매수 차단: {exc}")
        log("★LEAD_MA20_DATA")
    # 원자적 기록: 프로그램 재시작 후에도 당일 판단만 복원
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=STATE_PATH.parent,
                                         prefix=".kospi_ma20_", suffix=".tmp", delete=False) as f:
            tmp = f.name
            json.dump(record, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, STATE_PATH)
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)
    return record["allowed"]


def read_kospi_ma20_gate(trading_day=None):
    trading_day = trading_day or date.today()
    try:
        record = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return (record.get("trading_day") == trading_day.strftime("%Y%m%d")
                and record.get("allowed") is True and record.get("count") == 20)
    except (OSError, ValueError, TypeError):
        return False
