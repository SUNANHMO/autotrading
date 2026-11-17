from datetime import datetime
from c2_program import get_account_info, get_cash, get_asset

ETF_CODES = {"069500", "114800"}

def _to_int(value):
	try:
		return int(str(value or "0").replace(",", "").replace("+", "").strip())
	except (ValueError, TypeError):
		return 0

def _normalize_code(code):
	return str(code or "").replace("A", "").strip()

def get_account(token):
	date = datetime.today().strftime("%Y%m%d")
	return get_account_info(token, date)

def _parse_holdings(account):
	if not isinstance(account, dict):
		return []
	rows = account.get("stk_acnt_evlt_prst") or []
	holdings = []
	for item in rows:
		if not isinstance(item, dict):
			continue
		code = _normalize_code(item.get("stk_cd"))
		qty = _to_int(item.get("rmnd_qty"))
		if not code or qty <= 0:
			continue
		holdings.append({
			"code": code,
			"name": item.get("stk_nm"),
			"qty": qty,
			"buy_price": _to_int(item.get("avg_prc")),
		})

	return holdings


def get_account_summary(token):
	account = get_account(token)

	if account is None:
		return {
			"account": None,
			"cash": None,
			"asset": None,
			"holding": None,
			"holdings": [],
			"lead_stock_holding": None,
			"etf_holding": None,
			"has_holding": False,
			"has_lead_stock_holding": False,
			"has_etf_holding": False,
		}

	holdings = _parse_holdings(account)

	etf_holding = next(
		(item for item in holdings if item["code"] in ETF_CODES),
		None,
	)

	lead_stock_holding = next(
		(item for item in holdings if item["code"] not in ETF_CODES),
		None,
	)

	return {
		"account": account,
		"cash": get_cash(account=account),
		"asset": get_asset(account=account),

		# 기존 코드와의 호환성을 위해 첫 보유 종목도 유지
		"holding": holdings[0] if holdings else None,

		"holdings": holdings,
		"lead_stock_holding": lead_stock_holding,
		"etf_holding": etf_holding,

		"has_holding": bool(holdings),
		"has_lead_stock_holding": lead_stock_holding is not None,
		"has_etf_holding": etf_holding is not None,
	}
