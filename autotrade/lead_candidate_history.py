"""날짜별 주도주 후보 이력. Git 작업 디렉터리 밖에 영구 저장."""
import json
import os
import tempfile
from pathlib import Path

HISTORY_PATH = Path(os.environ.get(
    "LEAD_CANDIDATE_HISTORY_PATH",
    str(Path.home() / "lead_candidate_history.json"),
)).expanduser()


def save_candidate_history(trading_day, candidates, selected, ma20_pass, ma20_enabled):
    path = HISTORY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        history = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(history, dict):
            raise ValueError("이력 파일이 JSON 객체가 아닙니다")
    except FileNotFoundError:
        history = {}
    history[trading_day.strftime("%Y-%m-%d")] = {
        "kospi_ma20_pass": bool(ma20_pass),
        "kospi_ma20_enabled": bool(ma20_enabled),
        "candidates": list(candidates),
        "selected": selected,
    }
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent,
            prefix=".lead_candidate_", suffix=".tmp", delete=False,
        ) as f:
            tmp = f.name
            json.dump(history, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)
    print(f"[LEAD HISTORY] {trading_day} 기록: {path}")
