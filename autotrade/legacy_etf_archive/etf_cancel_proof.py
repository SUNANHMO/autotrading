"""취소 증빙의 보수적 검증. 실제 API 응답 필드 매핑 전에는 승인하지 않는다."""


def validate_cancel_proof(proof, *, original_order_no, code):
    """검증된 외부 거래내역 어댑터의 정규화 결과만 승인한다.

    proof: {'original_order_no': str, 'code': str,
            'cancel_status': 'CONFIRMED', 'remaining_qty': 0,
            'source_verified': True, 'complete_history': True}
    source_verified/complete_history는 실제 API 조회 검증자가 설정해야 한다.
    이 함수는 API 원문을 임의로 추정하지 않는다.
    """
    if not isinstance(proof, dict):
        return False
    if proof.get('source_verified') is not True or proof.get('complete_history') is not True:
        return False
    if str(proof.get('original_order_no', '')).strip() != str(original_order_no).strip():
        return False
    if str(proof.get('code', '')).removeprefix('A').strip() != code:
        return False
    if proof.get('cancel_status') != 'CONFIRMED':
        return False
    return type(proof.get('remaining_qty')) is int and proof['remaining_qty'] == 0
