"""삼성전자 프로그램 수급의 읽기 전용 가상 재생.

주의: 이 결과는 계좌 보유·미체결과 대조하기 전까지 실제 주문에 사용하지 않는다.
"""
import json
import os
from datetime import datetime

from a_config import REVERSE_AMOUNT

HISTORY_FILE = "program_history.json"


def parse_amount(raw):
    """기존 ka90008 금액 표기(+3313, -3313, --3313)를 정수로 변환."""
    if isinstance(raw, bool) or raw is None:
        raise ValueError("금액 누락 또는 잘못된 형식")
    value = str(raw).strip().replace(",", "")
    if value.startswith("--"):
        value = "-" + value[2:]
    if not value or value in ("+", "-"):
        raise ValueError("금액이 비어 있음")
    return int(value)


def replay_program_history(history_file=None, now=None, max_age_seconds=180):
    """당일 09시 이후 기록을 검증한 후 가상 포지션을 재생한다.

    파일 및 계좌 상태는 변경하지 않는다. 데이터가 불확실하면 예외로 중단한다.
    """
    now = now or datetime.now()
    path = history_file or HISTORY_FILE
    if not isinstance(max_age_seconds, (int, float)) or max_age_seconds < 0:
        raise ValueError("최신성 허용 시간이 잘못됨")
    if not ("090100" <= now.strftime("%H%M%S") < "152000"):
        raise ValueError("장중 09:01~15:20에만 복구 재생 허용")

    # 기존 JSON은 날짜 메타데이터가 없으므로 수정 시각으로 당일 생성 여부를 확인한다.
    # 이는 데이터 출처의 완전성을 증명하지 않으므로 별도 검증이 필요하다.
    modified = datetime.fromtimestamp(os.stat(path).st_mtime)
    if modified.date() != now.date() or modified > now:
        raise ValueError("과거 수급 파일 날짜 또는 수정 시각이 올바르지 않음")

    with open(path, "r", encoding="utf-8") as file:
        source_rows = json.load(file)
    if not isinstance(source_rows, list) or not source_rows:
        raise ValueError("과거 수급 데이터가 비어 있거나 리스트가 아님")

    today = now.strftime("%Y%m%d")
    current = now.strftime("%H%M%S")
    rows = []
    seen_times = set()
    for index, row in enumerate(source_rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f"{index}번째 행 형식 오류")
        tm = str(row.get("tm", "")).strip()
        if len(tm) != 6 or not tm.isdigit():
            raise ValueError(f"{index}번째 시간 형식 오류: {tm!r}")
        try:
            datetime.strptime(tm, "%H%M%S")
        except ValueError as exc:
            raise ValueError(f"{index}번째 시간 값 오류: {tm}") from exc
        if tm in seen_times:
            raise ValueError(f"중복 수급 시간: {tm}")
        seen_times.add(tm)
        if row.get("date") not in (None, "", today):
            raise ValueError(f"{tm} 조회 날짜 불일치")
        if row.get("stk_cd") not in (None, "", "005930"):
            raise ValueError(f"{tm} 종목코드 불일치")
        try:
            net = parse_amount(row["prm_netprps_amt"])
            buy = parse_amount(row["prm_buy_amt"])
            sell = parse_amount(row["prm_sell_amt"])
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError(f"{tm} 수급 금액 파싱 실패") from exc
        if buy < 0 or sell < 0 or net != buy - sell:
            raise ValueError(f"{tm} 수급 금액 검증 실패")
        if "090000" <= tm <= "152000":
            if tm > current:
                raise ValueError(f"현재 시각 이후 수급 기록: {tm}")
            rows.append((tm, net))

    rows.sort()
    if not rows or rows[0][0] > "090100":
        raise ValueError("09:00~09:01 시작 기록 누락")
    last_dt = datetime.strptime(today + rows[-1][0], "%Y%m%d%H%M%S")
    age = (now - last_dt).total_seconds()
    if not 0 <= age <= max_age_seconds:
        raise ValueError(f"과거 수급 최신성 부족: {age:.0f}초")

    position = "NONE"
    high = low = current_net = 0
    signals = 0
    for tm, net in rows:
        current_net = net
        if position == "NONE":
            if net >= REVERSE_AMOUNT:
                position = "KODEX200"
            elif net <= -REVERSE_AMOUNT:
                position = "INVERSE"
            else:
                continue
            high = low = net
            signals += 1
        elif position == "INVERSE":
            low = min(low, net)
            if net >= low + REVERSE_AMOUNT:
                position = "KODEX200"
                high = low = net
                signals += 1
        else:
            high = max(high, net)
            if net <= high - REVERSE_AMOUNT:
                position = "INVERSE"
                high = low = net
                signals += 1

    return {
        "position": position,
        "current_net_amount": current_net,
        "high_net_amount": high,
        "low_net_amount": low,
        "last_time": rows[-1][0],
        "total_rows": len(rows),
        "skipped_rows": 0,
        "signal_count": signals,
    }


if __name__ == "__main__":
    print("이 모듈은 자동 실행하지 않습니다. 테스트에서만 replay_program_history()를 호출하세요.")
