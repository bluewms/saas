from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase


class TestFieldsGet(TransactionCase):
    def test_cannot_assign_unheld_group(self):
        user = self.env.ref('base.user_demo')
        administration = self.env.ref('base.group_erp_manager')
        settings = self.env.ref('base.group_system')
        user.group_ids = [Command.unlink(settings.id), Command.link(administration.id)]
        self.assertFalse(user.has_group('base.group_system'))

        with self.assertRaises(AccessError):
            user.with_user(user).write({'group_ids': [Command.link(settings.id)]})

        self.assertFalse(user.has_group('base.group_system'))
