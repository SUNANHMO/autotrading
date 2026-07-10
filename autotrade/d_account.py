from b_auth import get_token
from datetime import datetime
from telegram_log import log
from c2_program import (get_account_info, get_cash, get_asset, get_holding, has_holding)

def get_account(token):
	date = datetime.today().strftime("%Y%m%d")
	return get_account_info(token, date)


def get_account_summary(token):
	account = get_account(token)

	return {
		"account": account,
		"cash": get_cash(account=account),
		"asset": get_asset(account=account),
		"holding": get_holding(account=account),
		"has_holding": has_holding(account=account)}