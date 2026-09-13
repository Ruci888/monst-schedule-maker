import unittest
from service import App
from test_service import MemoryStore, KEY

ORIGIN = 'https://kourin-register.anzai2348.chatgpt.site'
class CorsTests(unittest.TestCase):
    def call(self, origin, method='OPTIONS', auth=''):
        response = {}
        def start(status, headers):
            response.update(code=int(status.split()[0]), headers=dict(headers))
        App(MemoryStore(), KEY, ORIGIN)({'HTTP_ORIGIN':origin, 'REQUEST_METHOD':method,
            'HTTP_ACCESS_CONTROL_REQUEST_METHOD':'POST', 'HTTP_AUTHORIZATION':auth,
            'PATH_INFO':'/v1/master'}, start)
        return response
    def test_preflight_needs_no_key(self):
        r=self.call(ORIGIN)
        self.assertEqual(r['code'],200)
        self.assertEqual(r['headers']['Access-Control-Allow-Origin'],ORIGIN)
    def test_other_origin_is_denied(self):
        r=self.call('https://other.invalid', 'GET', 'Bearer '+KEY)
        self.assertEqual(r['code'],403)
        self.assertNotIn('Access-Control-Allow-Origin',r['headers'])
    def test_cors_does_not_replace_auth(self):
        r=self.call(ORIGIN, 'GET')
        self.assertEqual(r['code'],401)
        self.assertEqual(r['headers']['Access-Control-Allow-Origin'],ORIGIN)
    def test_authenticated_master_can_be_read(self):
        self.assertEqual(self.call(ORIGIN, 'GET', 'Bearer '+KEY)['code'],200)
