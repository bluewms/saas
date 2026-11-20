# License MIT (https://opensource.org/licenses/MIT).
from odoo import models
from odoo.exceptions import AccessError


class IrModuleModule(models.Model):
    _inherit = 'ir.module.module'

    def _check_direct_app_management(self):
        if not self.env.su and not self.env.user.has_group('access_apps.group_allow_apps'):
            raise AccessError(self.env._('You are not allowed to manage installed apps directly.'))

    def button_install(self):
        self._check_direct_app_management()
        return super().button_install()

    def button_uninstall(self):
        self._check_direct_app_management()
        return super().button_uninstall()

    def button_upgrade(self):
        self._check_direct_app_management()
        return super().button_upgrade()
