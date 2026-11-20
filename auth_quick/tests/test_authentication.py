# License MIT (https://opensource.org/licenses/MIT).
from unittest.mock import patch
from urllib.parse import urlsplit

from lxml import html

from odoo.tests.common import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestAuthQuick(HttpCase):
    def test_token_confirmation_uses_server_build_reference(self):
        admin = self.env.ref('base.user_admin')
        config = self.env['ir.config_parameter']
        config.set_str('auth_quick.master', 'http://issuer.example.com')
        config.set_str('auth_quick.build', '42')
        token = 'test-token'
        route = '/auth_quick/check-token'

        with patch('odoo.addons.auth_quick.controllers.main.requests.post') as post:
            response = self.url_open(route, params={'token': token})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')
            post.assert_not_called()
            csrf = html.fromstring(response.content).xpath('//input[@name="csrf_token"]/@value')[0]

            issuer = post.return_value
            issuer.status_code = 200
            issuer.json.return_value = {
                'result': {'success': 'ok', 'data': {'build': '99', 'build_user_id': admin.id}},
            }
            form = {'csrf_token': csrf, 'token': token}
            self.assertEqual(self.url_open(route, data=form, allow_redirects=False).status_code, 403)

            issuer.json.return_value['result']['data']['build'] = '42'
            response = self.url_open(route, data=form, allow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(urlsplit(response.headers['Location']).path, '/odoo')
            self.assertEqual(post.call_args.kwargs['json']['params'], {'token': token, 'build': '42'})
            self.assertFalse(post.call_args.kwargs['allow_redirects'])
