"""Проверки защиты ключа при обращениях к RouterAI."""
import unittest
from unittest.mock import patch
from urllib.request import Request

from src import routerai


class RouterAISecurityTest(unittest.TestCase):
    def test_disallowed_base_is_rejected_before_network_call(self):
        with patch('src.service.allowed_base_urls', return_value={'https://trusted.example/api/v1'}), \
             patch.object(routerai._opener, 'open') as open_request:
            with self.assertRaises(routerai.ProviderError):
                routerai.request_json('https://attacker.example/api/v1', 'secret-value', '/models')
        open_request.assert_not_called()

    def test_redirect_handler_refuses_forwarding_authorization(self):
        handler = routerai._RejectRedirects()
        request = Request('https://trusted.example/api/v1/models', headers={'Authorization': 'Bearer secret-value'})
        redirected = handler.redirect_request(
            request, None, 302, 'Found', {'Location': 'https://attacker.example/collect'},
            'https://attacker.example/collect')
        self.assertIsNone(redirected)


if __name__ == '__main__':
    unittest.main()
