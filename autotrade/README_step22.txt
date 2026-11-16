22단계: ETF 통합 회귀 테스트 (읽기 전용)

추가할 파일: test_etf_integration_step22.py (신규)
기존 운영 코드 변경 없음. 서버 재시작 불필요.

실행:
cd /root/autotrading/autotrade
python -m py_compile test_etf_integration_step22.py
python test_etf_integration_step22.py

예상 출력: 33 integration tests passed

필요한 기존 파일: etf_scheduler_diagnostic_step21.py, etf_partial_reconcile_step19.py,
etf_virtual_alignment_step18.py, etf_closing_plan_step20.py,
etf_cancel_verify_step17.py, etf_cancel_history_step15.py, etf_cancel_proof.py

범위: 가상/실제 정합성, 미체결/부분체결 불확실성, 취소 증빙 보류,
15:20~15:30 청산 판단, 입력 불변성, 모든 경로 주문 금지.

주의: 합성 데이터만 사용. 실계좌 주문/취소 실행, API 호출, 스케줄러 통합 실시간 검증이 아님.
