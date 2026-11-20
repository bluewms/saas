# Copyright 2018 Ivan Yelizariev <https://it-projects.info/team/yelizariev>
# License MIT (https://opensource.org/licenses/MIT).
from odoo import models
from odoo.exceptions import AccessDenied


# Only the controller can pass this in-memory proof after issuer verification.
VERIFIED_LOGIN = object()


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _check_credentials(self, credential, env):
        if credential.get('type') != 'auth_quick':
            return super()._check_credentials(credential, env)
        if credential.get('proof') is not VERIFIED_LOGIN or credential.get('uid') != self.id:
            raise AccessDenied()
        return {'uid': self.id, 'auth_method': 'auth_quick', 'mfa': 'default'}
