"""당일 삼성전자 프로그램 순매수 전체 이력을 키움 API에서 새로 조회해 저장한다.
사용: python manual_archive_today.py
"""
from datetime import datetime
from b_auth import get_token
from h_schedule import check_program_history
from etf_history_archive import archive_program_history


def main():
    token = get_token()
    if not token:
        raise SystemExit("키움 인증 토큰을 받지 못했습니다")
    rows = check_program_history(token, "005930", persist_live=False)
    if not rows:
        raise SystemExit("전체 이력 신규 조회/검증 실패: 날짜별 파일을 변경하지 않았습니다")
    path, count, updated = archive_program_history(
        rows, trading_date=datetime.now().strftime("%Y%m%d")
    )
    print(f"저장 결과: {path}, {count}건, {'갱신' if updated else '기존 파일 유지'}")
    print(f"기록 구간: {min(row['tm'] for row in rows)} ~ {max(row['tm'] for row in rows)}")


if __name__ == "__main__":
    main()
