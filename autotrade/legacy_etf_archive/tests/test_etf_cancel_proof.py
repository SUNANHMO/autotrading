import sys
from pathlib import Path as _TestPath
sys.path.insert(0, str(_TestPath(__file__).resolve().parent.parent))

from etf_cancel_proof import validate_cancel_proof

base = dict(original_order_no='0187061', code='069500', cancel_status='CONFIRMED', remaining_qty=0, source_verified=True, complete_history=True)
assert validate_cancel_proof(base, original_order_no='0187061', code='069500')
for changes in ({'source_verified': False}, {'complete_history': False}, {'cancel_status':'REQUEST_ACCEPTED'}, {'remaining_qty': 3}, {'original_order_no':'other'}, {'code':'114800'}, {'remaining_qty':'0'}):
    assert not validate_cancel_proof({**base, **changes}, original_order_no='0187061', code='069500')
assert not validate_cancel_proof(None, original_order_no='0187061', code='069500')
print('9 tests passed')
