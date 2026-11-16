# 자동매매 프로젝트 구조 (정리 1차)

## 실행 경로 (기존 동작 유지)
- `h_schedule.py`: 스케줄러 진입점. `restart.sh`의 실행 경로는 변경하지 않음.
- `a_config.py`, `b_auth.py`, `c0_buy_selector.py`, `c2_program.py`, `d_account.py`, `e_state.py`, `f_order.py`, `g_websk.py`, `i_healthcheck.py`, `telegram_log.py`: 기존 공통/주도주 전략 및 API. 변경 없음.
- `etf_strategy.py`, `etf_virtual_strategy.py`: 기존 ETF 신호/가상 전략. **아직 이원화 상태**.
- `etf_execution.py`, `etf_order_manager.py`, `etf_state.py`: ETF 주문/상태 처리.
- `etf_recovery.py`, `etf_recovery_check.py`, `etf_step11_diagnostic.py`, `etf_scheduler_diagnostic_step21.py`, `etf_integration.py`, `etf_reconcile_plan.py`, `etf_fill_anchor.py`, `etf_partial_reconcile_step19.py`, `etf_virtual_alignment_step18.py`, `etf_closing_plan_step20.py`: 운영 경로 또는 그 의존성에서 사용하므로 이번에는 삭제하지 않음.
- `etf_cancel_proof.py`, `etf_cancel_reconcile.py`, `etf_cancel_history_step15.py`, `etf_cancel_verify_step17.py`, `etf_cancel_inspect_step16.py`, `etf_history_inspect_step14.py`, `etf_step23_audit.py`: 검증/진단 코드. 호출 관계를 확인하기 전까지 보존.

## 테스트
- `tests/`: 기존 `test_*.py` 파일 17개를 모아둔 디렉터리. 각각 `python tests/파일명.py`로 실행 가능.
- 각 테스트에 프로젝트 루트 import 경로만 추가. 테스트 내용 및 운영 코드는 변경하지 않음.

## 다음 통합 작업 (아직 미적용)
1. `etf_virtual_strategy.py` 최초 진입을 절대값 ±200억이 아니라 첫 관측 이후 고점/저점 대비 200억 변화로 수정.
2. `h_schedule.py`의 기존 `check_signal`과 1회성 리플레이를 실시간 가상 전략으로 일원화.
3. `etf_execution.py`가 가상 목표/실제 잔고/미체결을 비교하도록 연결.
4. 15:20 청산 경로 연결, 통합 검증 후 단계별 진단 모듈 정리.

**중요**: 이번 ZIP은 안전한 파일 배치 정리만 수행하며 ETF 자동 주문 차단은 해제하지 않습니다. 실제 주문 동작은 기존과 동일합니다.

## 통합 작업 진행 상황 (전략 규칙 수정)
- `etf_virtual_strategy.py`: 최초 진입도 순매수 절대값이 아니라 첫 관측 이후 고점/저점에서 20,000백만원(200억원) 변화로 판단하도록 수정.
- 예시 `+100억 → +180억 → -20억`은 인버스 최초 진입.
- `tests/test_virtual_initial_direction.py`: 최초 진입 방향 회귀 테스트 추가.
- `tests/test_virtual_step12.py`: 구 절대값 진입을 전제하던 테스트 입력을 새 기준에 맞게 수정.
- `etf_strategy.py`, `h_schedule.py`는 **아직 기존 실시간 판단 경로**를 사용함. 실시간 가상 전략 일원화 및 주문 실행 연결은 다음 통합 작업으로 남아 있음.
- ETF 실주문 차단은 해제하지 않음. 이 ZIP을 실전 자동매매 완성본으로 사용하면 안 됨.
