import os,unittest
from unittest.mock import patch
from server import healthy

class HealthTests(unittest.TestCase):
    def test_healthy(self):
        with patch.dict(os.environ,{'HEALTHY':'1'}):self.assertTrue(healthy())
    def test_unhealthy(self):
        with patch.dict(os.environ,{'HEALTHY':'0'}):self.assertFalse(healthy())
if __name__=='__main__':unittest.main()
