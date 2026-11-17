"""21단계: 읽기 전용 ETF 정합성 진단. 주문/취소/상태 변경 금지."""
from etf_partial_reconcile_step19 import reconcile_etf_snapshot
from etf_closing_plan_step20 import plan_etf_closing


def evaluate_step21(*, virtual_position, holdings, unfilled_orders, now_time,
                    account_verified=False, orders_verified=False,
                    lead_blocked=True, cancel_pending=True,
                    cancel_proof_verified=False, closing_order_pending=True):
    """스냅샷은 외부에서 획득. 불확실하면 차단, 주문 허가 없음."""
    result = {'status': 'VERIFY_REQUIRED', 'action': 'VERIFY_ACCOUNT_AND_ORDERS',
              'can_submit_order': False, 'pending_count': None,
              'actual_position': None, 'actual_qty': None}
    if not (account_verified is True and orders_verified is True):
        return result
    if not isinstance(now_time, str) or len(now_time) != 6 or not now_time.isdigit():
        return result
    if now_time >= '152000':
        plan = plan_etf_closing(
            now_time=now_time, holdings=holdings, unfilled_orders=unfilled_orders,
            account_verified=True, orders_verified=True,
            cancel_pending=cancel_pending,
            cancel_proof_verified=cancel_proof_verified,
            closing_order_pending=closing_order_pending)
        result.update(status='CLOSING_DIAGNOSTIC', action=plan['action'],
                      actual_qty=plan['actual_qty'], pending_count=plan['pending_count'])
    else:
        plan = reconcile_etf_snapshot(
            virtual_position=virtual_position, holdings=holdings,
            unfilled_orders=unfilled_orders, now_time=now_time,
            account_verified=True, orders_verified=True,
            lead_blocked=lead_blocked, cancel_pending=cancel_pending)
        result.update(status=plan['status'], action=plan['action'],
                      actual_position=plan['actual_position'], actual_qty=plan['actual_qty'],
                      pending_count=plan['pending_count'])
    result['can_submit_order'] = False
    return result


def query_and_evaluate_step21(token, virtual_position, now_time):
    """실계좌 조회만 수행; 취소/주문 상태는 안전상 미검증으로 취급."""
    result = {'status': 'QUERY_UNVERIFIED', 'action': 'VERIFY_ACCOUNT_AND_ORDERS',
              'can_submit_order': False}
    if not token:
        return result
    try:
        from d_account import get_account
        from c2_program import get_etf_unfilled_orders
        account = get_account(token)
        if (not isinstance(account, dict)
                or not isinstance(account.get('stk_acnt_evlt_prst'), list)):
            return result
        orders = get_etf_unfilled_orders(token)
        if not isinstance(orders, list):
            return result
        holdings = account['stk_acnt_evlt_prst']
        lead_blocked = any(
            str(row.get('stk_cd', '')).strip().removeprefix('A') not in ('069500', '114800')
            and int(str(row.get('rmnd_qty', '0')).replace(',', '').strip()) > 0
            for row in holdings if isinstance(row, dict))
        return evaluate_step21(
            virtual_position=virtual_position, holdings=holdings,
            unfilled_orders=orders, now_time=now_time,
            account_verified=True, orders_verified=True,
            lead_blocked=lead_blocked, cancel_pending=True,
            cancel_proof_verified=False, closing_order_pending=True)
    except (ValueError, TypeError, KeyError, OSError):
        return result
