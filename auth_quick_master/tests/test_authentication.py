from datetime import timedelta
from unittest.mock import patch

from lxml import html

from odoo import fields

from odoo.addons.base.tests.common import BaseCommon
from odoo.exceptions import AccessError
from odoo.tests.common import HttpCase, new_test_user, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestTokenAccess(BaseCommon):
    _test_user_groups = ('base.group_user', 'auth_quick_master.group_auth_quick')

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_user = new_test_user(
            cls.env, login='other_quick_user', groups='base.group_user,auth_quick_master.group_auth_quick',
        )

    def _issue_token(self):
        vals = self.env['auth_quick_master.token']._prepare_token_values('tenant', 42, 'tenant-admin')
        return self.env['auth_quick_master.token'].sudo().create(vals)

    def test_rpc_create_cannot_forge_token(self):
        with self.assertRaises(AccessError):
            self.env['auth_quick_master.token'].create({'build': 'tenant', 'token': 'chosen-token'})

    def test_secret_is_not_readable_by_quick_auth_user(self):
        token = self._issue_token().with_user(self.env.user)
        self.assertNotIn('token', token.fields_get())
        with self.assertRaises(AccessError):
            token.read(['token'])

    def test_other_users_cannot_read_token_record(self):
        token = self._issue_token().with_user(self.other_user)
        with self.assertRaises(AccessError):
            token.read(['build_login'])


@tagged('post_install', '-at_install')
class TestTokenEndpoint(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.quick_user = new_test_user(
            cls.env, login='quick_endpoint_user', password='quick_endpoint_password',
            groups='base.group_user,auth_quick_master.group_auth_quick',
        )

    def _check_token(self, token):
        response = self.url_open('/auth_quick_master/check-token', json=self.build_rpc_payload({'token': token}))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn('error', payload)
        return payload['result']

    def test_missing_token_returns_controlled_error(self):
        self.assertEqual(self._check_token('does-not-exist'), {'error': 'Invalid token'})
        self.assertEqual(self._check_token(False), {'error': 'Invalid token'})

    def test_token_is_consumed_once(self):
        token = self.env['auth_quick_master.token'].sudo().create({
            'user_id': self.quick_user.id, 'build': 'tenant', 'build_user_id': 42, 'build_login': 'tenant-admin',
        }).token
        self.assertEqual(self._check_token(token), {
            'success': 'ok', 'data': {'build_user_id': 42, 'build_login': 'tenant-admin', 'build': 'tenant'},
        })
        self.assertEqual(self._check_token(token), {'error': 'Invalid token'})

    def test_expired_token_is_rejected_and_removed(self):
        record = self.env['auth_quick_master.token'].sudo().create({
            'user_id': self.quick_user.id, 'build': 'tenant', 'build_user_id': 42,
        })
        token = record.token
        with patch.object(fields.Datetime, 'now', return_value=record.create_date + timedelta(minutes=6)):
            self.assertEqual(self._check_token(token), {'error': 'Token is obsolete'})
        self.assertEqual(self._check_token(token), {'error': 'Invalid token'})

    def test_get_does_not_issue_token_and_post_requires_csrf(self):
        self.authenticate(self.quick_user.login, 'quick_endpoint_password')
        Token = self.env['auth_quick_master.token'].sudo()
        count = Token.search_count([])
        params = {'build': 'tenant', 'build_user_id': 42, 'build_login': 'tenant-admin', 'build_url': 'https://tenant.example.com'}
        response = self.url_open('/auth_quick_master/get-token', params=params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Token.search_count([]), count)
        csrf = html.fromstring(response.content).xpath('//input[@name="csrf_token"]/@value')[0]
        with mute_logger('odoo.http'):
            rejected = self.url_open('/auth_quick_master/get-token', data=params, allow_redirects=False)
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(Token.search_count([]), count)
        response = self.url_open('/auth_quick_master/get-token', data={**params, 'csrf_token': csrf}, allow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Token.search_count([]), count + 1)
