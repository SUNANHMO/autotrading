23단계: 운영 준비도 정적 감사 (읽기 전용)

추가 파일: etf_step23_audit.py, test_etf_step23_audit.py
기존 운영 파일 교체 없음, 재시작 불필요.

명령:
cd /root/autotrading/autotrade
python -m py_compile etf_step23_audit.py test_etf_step23_audit.py
python test_etf_step23_audit.py
python etf_step23_audit.py

정적 점검은 코드 패턴 기반이며 운영 동작 전체를 증명하지 않습니다.
출력 AUTO_TRADE_READY: False는 보수적인 고정값입니다.
주문/취소/API/파일 상태 변경을 수행하지 않습니다.
