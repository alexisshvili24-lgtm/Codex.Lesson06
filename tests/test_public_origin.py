import unittest
from unittest.mock import patch

from fastapi import Request
from starlette.responses import Response

from app import local_origin


class PublicOriginTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, host, origin=None, path='/'):
        headers = [(b'host', host.encode('ascii')), (b'x-forwarded-host', b'localhost')]
        if origin is not None:
            headers.append((b'origin', origin.encode('ascii')))
        scope = {'type': 'http', 'method': 'GET', 'scheme': 'http', 'path': path,
                 'query_string': b'', 'headers': headers, 'server': ('testserver', 80)}
        async def next_handler(request):
            return Response(status_code=200)
        return await local_origin(Request(scope), next_handler)

    async def test_allowed_hosts_and_static(self):
        for host in ('localhost', '127.0.0.1', '179.254.162.130', 'LOCALHOST:80'):
            with self.subTest(host=host):
                self.assertEqual((await self.request(host)).status_code, 200)
        self.assertEqual((await self.request('179.254.162.130', path='/static/style.css')).status_code, 200)
        with patch.dict('os.environ', {'APP_ALLOWED_HOSTS': 'example.test'}):
            self.assertEqual((await self.request('example.test')).status_code, 200)

    async def test_host_and_origin_validation(self):
        cases = [
            ('179.254.162.130', 'http://179.254.162.130', 200),
            ('localhost:80', 'http://LOCALHOST', 200),
            ('localhost', 'https://localhost', 403),
            ('localhost:8025', 'http://localhost', 403),
            ('localhost', 'null', 403),
            ('localhost', 'http://localhost:0', 403),
            ('localhost', 'http://localhost/path', 403),
            ('localhost', 'http://evil.example', 403),
            ('other.example', None, 403),
            ('localhost:99999', None, 403),
            ('localhost:', None, 403),
            ('user@localhost', None, 403),
        ]
        for host, origin, status in cases:
            with self.subTest(host=host, origin=origin):
                self.assertEqual((await self.request(host, origin)).status_code, status)