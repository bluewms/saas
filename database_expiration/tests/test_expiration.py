# License MIT (https://opensource.org/licenses/MIT).
from odoo import fields
from odoo.tests.common import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestDatabaseExpiration(HttpCase):
    def test_expired_database_blocks_web_client(self):
        self.authenticate('admin', 'admin')
        config = self.env['ir.config_parameter']
        config.set_str('database_expiration_date', fields.Datetime.to_string(fields.Datetime.now().replace(year=2000)))
        response = self.url_open('/odoo')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Your database is expired', response.text)
        self.assertNotIn('odoo.__session_info__', response.text)
