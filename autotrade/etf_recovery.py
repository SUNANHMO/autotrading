
import json
from datetime import datetime

from a_config import REVERSE_AMOUNT


HISTORY_FILE = "program_history.json"


def parse_amount(raw):
    """
    키움 프로그램 순매수 금액 변환
    예:
        +3313  -> 3313
        -3313  -> -3313
        --3313 -> -3313
    """

    value = str(raw).strip().replace(",", "")

    if value.startswith("--"):
        return -int(value[2:])

    return int(value.replace("+", ""))


def replay_program_history():
    """
    과거 프로그램 수급 데이터를 시간순으로 재생한다.
    실제 ETF 상태 파일이나 주문에는 접근하지 않는다.
    """

    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        rows = json.load(f)

    # 09:00 이후 데이터만 사용
    rows = [
        row for row in rows
        if "090000" <= row.get("tm", "") <= "152000"
    ]

    rows.sort(key=lambda x: x["tm"])

    if not rows:
        raise ValueError("09시 이후 과거 수급 데이터가 없습니다.")

    position = "NONE"
    high_net_amount = 0
    low_net_amount = 0
    current_net_amount = 0

    signal_count = 0
    skipped_count = 0
    previous_time = None

    for row in rows:

        try:
            net_amount = parse_amount(
                row["prm_netprps_amt"]
            )

            # 매수 - 매도 금액과 교차 검증
            buy = parse_amount(row["prm_buy_amt"])
            sell = parse_amount(row["prm_sell_amt"])

            if net_amount != buy - sell:
                raise ValueError("순매수 금액 검증 실패")

        except (ValueError, KeyError, TypeError):
            skipped_count += 1
            print(
                f"[복구 오류] 시간={row.get('tm')} "
                f"수급 데이터 건너뜀"
            )
            continue

        current_net_amount = net_amount
        current_time = row["tm"]

        # 최초 진입
        if position == "NONE":

            if net_amount >= REVERSE_AMOUNT:
                position = "KODEX200"
                high_net_amount = net_amount
                low_net_amount = net_amount
                signal_count += 1

                print(
                    f"[가상 진입] {current_time} "
                    f"KODEX200, 수급={net_amount}"
                )

            elif net_amount <= -REVERSE_AMOUNT:
                position = "INVERSE"
                high_net_amount = net_amount
                low_net_amount = net_amount
                signal_count += 1

                print(
                    f"[가상 진입] {current_time} "
                    f"인버스, 수급={net_amount}"
                )

        # 인버스 보유 중
        elif position == "INVERSE":

            if net_amount < low_net_amount:
                low_net_amount = net_amount

            if net_amount >= low_net_amount + REVERSE_AMOUNT:

                position = "KODEX200"
                high_net_amount = net_amount
                low_net_amount = net_amount
                signal_count += 1

                print(
                    f"[가상 전환] {current_time} "
                    f"인버스 -> KODEX200, "
                    f"수급={net_amount}"
                )

        # KODEX200 보유 중
        elif position == "KODEX200":

            if net_amount > high_net_amount:
                high_net_amount = net_amount

            if net_amount <= high_net_amount - REVERSE_AMOUNT:

                position = "INVERSE"
                high_net_amount = net_amount
                low_net_amount = net_amount
                signal_count += 1

                print(
                    f"[가상 전환] {current_time} "
                    f"KODEX200 -> 인버스, "
                    f"수급={net_amount}"
                )

        previous_time = current_time

    result = {
        "position": position,
        "current_net_amount": current_net_amount,
        "high_net_amount": high_net_amount,
        "low_net_amount": low_net_amount,
        "last_time": previous_time,
        "total_rows": len(rows),
        "skipped_rows": skipped_count,
        "signal_count": signal_count,
    }

    print("\n===== ETF 과거 데이터 복구 결과 =====")
    for key, value in result.items():
        print(f"{key}: {value}")

    return result


if __name__ == "__main__":
    replay_program_history()
