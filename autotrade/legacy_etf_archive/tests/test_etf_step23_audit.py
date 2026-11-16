"""No imports of trading modules, no API calls."""
import sys
from pathlib import Path as _TestPath
sys.path.insert(0, str(_TestPath(__file__).resolve().parent.parent))

import tempfile
from pathlib import Path
from etf_step23_audit import audit, REQUIRED

def test():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        issues = audit(root)
        assert sum(code == 'MISSING_FILE' for code, _ in issues) == len(REQUIRED)
        (root/'h_schedule.py').write_text('async def main():\n    etf_recovery_completed = False\n    executed["history_test"] = True\n    replay_virtual_strategy([])\n\ndef monitor_etf_signal():\n    check_signal(1,2,3)\n')
        issues = audit(root)
        codes = {code for code, _ in issues}
        assert 'ETF_ORDER_GATE_CLOSED' in codes
        assert 'VIRTUAL_REPLAY_ONE_SHOT' in codes
        assert 'LIVE_VIRTUAL_NOT_WIRED' in codes
        assert 'CLOSING_EXECUTION_NOT_WIRED' in codes
        (root/'etf_cancel_verify_step17.py').write_text("x = {'proof_approved': False}\n")
        (root/'etf_scheduler_diagnostic_step21.py').write_text("x = {'can_submit_order': False}\n")
        codes = {code for code, _ in audit(root)}
        assert 'CANCEL_PROOF_NOT_APPROVED' in codes
        assert 'SCHEDULER_READ_ONLY' in codes
        (root/'h_schedule.py').write_text('invalid python !!!')
        assert any(code == 'UNREADABLE_SOURCE' for code, _ in audit(root))
    print('8 checks passed')

if __name__ == '__main__':
    test()
