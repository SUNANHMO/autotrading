import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
import etf_state
from etf_strategy import update_virtual_position
from etf_execution import reconcile_etf

class SimpleETFTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = etf_state.STATE_FILE
        etf_state.STATE_FILE = str(Path(self.tmp.name) / 'state.json')
    def tearDown(self):
        etf_state.STATE_FILE = self.old
        self.tmp.cleanup()
    def test_initial_inverse(self):
        self.assertEqual(update_virtual_position(10000, trading_date='20261116'),'NONE')
        self.assertEqual(update_virtual_position(18000, trading_date='20261116'),'NONE')
        self.assertEqual(update_virtual_position(-2000, trading_date='20261116'),'INVERSE')
    def test_switches(self):
        for n in (10000,18000,-2000,-30000): update_virtual_position(n,trading_date='20261116')
        self.assertEqual(update_virtual_position(-10000,trading_date='20261116'),'KODEX200')
    def test_no_orders_if_aligned(self):
        with patch('etf_execution._account_qty',return_value={'069500':12,'114800':0}),patch('etf_execution.get_etf_unfilled_orders',return_value=[]):
            self.assertEqual(reconcile_etf('token',None,'KODEX200'),'ALIGNED')
    def test_pending_no_reprice(self):
        with patch('etf_execution._account_qty',return_value={'069500':0,'114800':0}),patch('etf_execution.get_etf_unfilled_orders',return_value=[{'stk_cd':'069500','io_tp_nm':'매수','ord_no':'123'}]):
            self.assertEqual(reconcile_etf('token',None,'KODEX200'),'WAIT_FILL')

if __name__=='__main__': unittest.main()
