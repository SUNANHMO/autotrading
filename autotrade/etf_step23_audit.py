"""23단계: 소스 정적 점검. import/네트워크/주문/상태변경 없음."""
import ast
from pathlib import Path

REQUIRED = ('h_schedule.py','etf_execution.py','etf_cancel_proof.py',
            'etf_virtual_strategy.py','etf_scheduler_diagnostic_step21.py',
            'etf_closing_plan_step20.py','etf_cancel_verify_step17.py')

def audit(root):
    root = Path(root)
    issues = []
    trees = {}
    for name in REQUIRED:
        path = root / name
        if not path.is_file():
            issues.append(('MISSING_FILE', name))
            continue
        try:
            trees[name] = ast.parse(path.read_text(encoding='utf-8'), filename=name)
        except (SyntaxError, UnicodeError, OSError) as exc:
            issues.append(('UNREADABLE_SOURCE', name + ': ' + type(exc).__name__))
    if 'h_schedule.py' in trees:
        tree = trees['h_schedule.py']
        main = next((x for x in tree.body if isinstance(x, ast.AsyncFunctionDef) and x.name == 'main'), None)
        if main is None:
            issues.append(('NO_MAIN', 'h_schedule.py'))
        else:
            flags = [x.value.value for x in ast.walk(main)
                     if isinstance(x, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == 'etf_recovery_completed' for t in x.targets)
                     and isinstance(x.value, ast.Constant) and isinstance(x.value.value, bool)]
            if flags and all(v is False for v in flags):
                issues.append(('ETF_ORDER_GATE_CLOSED', 'etf_recovery_completed=False'))
            else:
                issues.append(('ETF_ORDER_GATE_REVIEW', 'ETF 주문 게이트 수동 검토 필요'))
        src = (root / 'h_schedule.py').read_text(encoding='utf-8')
        if 'executed["history_test"] = True' in src and 'replay_virtual_strategy' in src:
            issues.append(('VIRTUAL_REPLAY_ONE_SHOT', 'history_test 완료 후 반복 재생 확인 필요'))
        funcs = {x.name: x for x in tree.body if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))}
        monitor = funcs.get('monitor_etf_signal')
        if monitor:
            calls = {n.func.id for n in ast.walk(monitor) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
            if 'check_signal' in calls and 'replay_virtual_strategy' not in calls:
                issues.append(('LIVE_VIRTUAL_NOT_WIRED', '실시간 경로는 기존 check_signal 사용'))
        if not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'plan_etf_closing'
                   for n in ast.walk(tree)):
            issues.append(('CLOSING_EXECUTION_NOT_WIRED', '스케줄러에서 장마감 실행 연동 확인 불가'))
    if 'etf_cancel_verify_step17.py' in trees:
        src = (root / 'etf_cancel_verify_step17.py').read_text(encoding='utf-8')
        if "'proof_approved': False" in src:
            issues.append(('CANCEL_PROOF_NOT_APPROVED', '17단계 검증은 증빙 승인하지 않음'))
    if 'etf_scheduler_diagnostic_step21.py' in trees:
        src = (root / 'etf_scheduler_diagnostic_step21.py').read_text(encoding='utf-8')
        if "'can_submit_order': False" in src or "result['can_submit_order'] = False" in src:
            issues.append(('SCHEDULER_READ_ONLY', '21단계 진단은 주문 허가하지 않음'))
    return issues


def main():
    issues = audit(Path(__file__).resolve().parent)
    print('STEP23_STATIC_AUDIT')
    for code, detail in issues:
        print(f'{code}: {detail}')
    print('READ_ONLY: True')
    print('AUTO_TRADE_READY: False')

if __name__ == '__main__':
    main()
