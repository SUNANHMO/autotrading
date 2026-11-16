"""최초 수급 변화폭에 의한 ETF 가상 진입 회귀 테스트."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from etf_virtual_strategy import replay_virtual_strategy

def row(i, net):
    return {"tm": f"09{i:02d}00", "prm_netprps_amt": str(net),
            "prm_buy_amt": str(max(net, 0)), "prm_sell_amt": str(max(-net, 0))}

def check(values, expected):
    result = replay_virtual_strategy([row(i, x) for i, x in enumerate(values)])
    assert [t["to"] for t in result["transitions"]] == expected, result

check([10000, 18000, -2000], ["INVERSE"])
check([10000, -10000], ["INVERSE"])
check([-10000, 10000], ["KODEX200"])
check([50000, 30000], ["INVERSE"])
check([-50000, -30000], ["KODEX200"])
check([10000, 18000, 17000], [])
check([10000, 18000, -2000, -30000, -10000], ["INVERSE", "KODEX200"])
print("7 initial-direction tests passed")
