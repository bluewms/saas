# Copyright 2016 Jairo Llopis <jairo.llopis@tecnativa.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from types import SimpleNamespace
from unittest.mock import patch

from lxml.html import document_fromstring

from odoo.exceptions import UserError
from odoo.tests.common import HttpCase
from odoo.tools.misc import mute_logger


class UICase(HttpCase):
    def setUp(self):
        super().setUp()
        if 'auth_signup_uninvited' in self.env['website']._fields:
            self.env.ref('base.default_website').auth_signup_uninvited = 'b2c'
        self.env['ir.config_parameter'].set_str('auth_signup.invitation_scope', 'b2c')
        page = document_fromstring(self.url_open('/web/signup').content)
        self.data = {'csrf_token': page.xpath("//input[@name='csrf_token']/@value")[0], 'name': 'Somebody'}

    def test_bad_email(self):
        response = self.url_open('/web/signup', data={**self.data, 'login': 'bad email'})
        self.assertIn('Please enter a valid email address', response.text)

    @mute_logger('odoo.http')
    def test_failed_recaptcha(self):
        login = 'test-verification@odoo.com'
        with patch.object(type(self.env['ir.http']), '_verify_request_recaptcha_token', side_effect=UserError('CAPTCHA test')):
            response = self.url_open('/web/signup', data={**self.data, 'login': login})
        self.assertEqual(response.status_code, 422)
        self.assertFalse(self.env['res.users'].search([('login', '=', login)]))

    def test_signup_password_cannot_bypass_email_verification(self):
        login = 'test-verification@odoo.com'
        with (
            patch('odoo.addons.auth_signup_verify_email.controllers.main.validate_email',
                  return_value=SimpleNamespace(normalized=login)),
            patch.object(type(self.env['res.users']), 'reset_password') as reset,
        ):
            response = self.url_open('/web/signup', data={
                **self.data, 'login': login, 'password': 'submitted-password',
                'confirm_password': 'submitted-password',
            })
        self.assertIn('Check your email to activate your account', response.text)
        reset.assert_called_once_with(login)
