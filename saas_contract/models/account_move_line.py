from odoo import fields, models
from odoo.exceptions import AccessError


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    saas_service_applied = fields.Boolean(
        'SaaS service applied', readonly=True, copy=False, groups='base.group_system',
    )

    def write(self, vals):
        if 'saas_service_applied' in vals and not self.env.su:
            raise AccessError(self.env._('SaaS payment application is managed by the payment hook.'))
        return super().write(vals)
