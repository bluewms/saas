from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResUsers(models.Model):
    _inherit = 'res.users'

    is_excluded_from_limiting = fields.Boolean(default=False, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and any(vals.get('is_excluded_from_limiting') for vals in vals_list):
            raise ValidationError(self.env._('Only the superuser can exclude a user from the limit.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'is_excluded_from_limiting' in vals and not self.env.su:
            raise ValidationError(self.env._('Only the superuser can change user limit exclusions.'))
        return super().write(vals)
