"""검증된 프로그램 수급 이력을 날짜별 분석용 최소 JSON으로 보관한다."""
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from a_config import KRX_TAKE_PROFIT_TIME, CANCEL_TAKE_PROFIT_TIME


def archive_program_history(rows, *, trading_date=None, directory=None):
    """검증된 API 조회 행을 tm/순매수만 보관. 기존의 더 완전한 파일은 보호."""
    if not rows:
        raise ValueError("저장할 수급 이력이 없습니다")
    day = trading_date or datetime.now().strftime("%Y%m%d")
    if len(day) != 8 or not day.isdigit() or datetime.strptime(day, "%Y%m%d").strftime("%Y%m%d") != day:
        raise ValueError("날짜 형식 오류")
    if datetime.strptime(day, "%Y%m%d").weekday() >= 5:
        raise ValueError("주말 날짜로 수급 이력을 저장할 수 없습니다")
    directory = Path(directory) if directory is not None else Path(__file__).resolve().parent
    output = directory / f"program_history_{day}.json"
    simplified = []
    seen = {}
    for row in rows:
        tm = str(row["tm"]).strip()
        if len(tm) != 6 or not tm.isdigit():
            raise ValueError(f"시간 형식 오류: {tm}")
        datetime.strptime(tm, "%H%M%S")
        if not (KRX_TAKE_PROFIT_TIME.replace(":", "") <= tm <= CANCEL_TAKE_PROFIT_TIME.replace(":", "")):
            continue
        # 검증된 원본 값의 단위(백만원)를 유지한다.
        raw = str(row["prm_netprps_amt"]).replace(",", "").replace("--", "-")
        net = int(raw)
        # 보관 전용: 입력 순서상 마지막 값을 채택한다.
        seen[tm] = net
    simplified = [
        {"tm": tm, "prm_netprps_amt": net}
        for tm, net in sorted(seen.items())
    ]
    if not simplified:
        raise ValueError(f"{KRX_TAKE_PROFIT_TIME}~{CANCEL_TAKE_PROFIT_TIME} 범위의 수급 기록이 없습니다")
    # 기존 날짜 파일이 더 늦은 시각 또는 더 많은 기록을 담으면 덮어쓰지 않는다.
    if output.exists():
        with output.open(encoding="utf-8") as f:
            previous = json.load(f)
        if not isinstance(previous, list):
            raise ValueError("기존 날짜 파일 형식 오류")
        old_times = [str(item["tm"]) for item in previous]
        if old_times and (max(old_times) > simplified[-1]["tm"] or
                          (max(old_times) == simplified[-1]["tm"] and len(previous) >= len(simplified))):
            return str(output), len(previous), False
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                         prefix=".program_archive_", suffix=".tmp", delete=False) as f:
            tmp_path = f.name
            json.dump(simplified, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, output)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
    return str(output), len(simplified), True
