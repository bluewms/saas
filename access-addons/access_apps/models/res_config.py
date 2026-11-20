# Copyright 2018,2021 Ivan Yelizariev <https://it-projects.info/team/yelizariev>
# Copyright 2018 Ildar Nasyrov <https://it-projects.info/team/iledarn>
# License MIT (https://opensource.org/licenses/MIT).

from odoo import api, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    @api.model
    def _install_modules(self, modules):
        if self.env.user.has_group('access_apps.group_allow_apps_only_from_settings'):
            return super(ResConfigSettings, self.sudo())._install_modules(modules)
        return super()._install_modules(modules)

    def execute(self):
        self.ensure_one()
        if self.env.user.has_group('access_apps.group_allow_apps_only_from_settings'):
            to_uninstall = self._get_classified_fields()['module'].filtered(
                lambda module: module.state in ('installed', 'to upgrade') and not self[f'module_{module.name}']
            )
            result = super().execute()
            if to_uninstall:
                to_uninstall.sudo().button_immediate_uninstall()
            return result
        return super().execute()
