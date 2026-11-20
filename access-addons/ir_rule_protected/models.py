# License MIT (https://opensource.org/licenses/MIT).
from odoo import api, fields, models
from odoo.exceptions import AccessError


class IrAccess(models.Model):
    _inherit = 'ir.access'

    protected = fields.Boolean(help='Only the superuser can edit a protected access rule.')

    def _check_protected(self):
        if not self.env.su and any(self.sudo().mapped('protected')):
            raise AccessError(self.env._('You cannot change a protected access rule.'))

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and any(vals.get('protected') for vals in vals_list):
            raise AccessError(self.env._('Only the superuser can protect an access rule.'))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and vals.get('protected'):
            raise AccessError(self.env._('Only the superuser can protect an access rule.'))
        self._check_protected()
        return super().write(vals)

    def unlink(self):
        self._check_protected()
        return super().unlink()


class IrModuleModule(models.Model):
    _inherit = 'ir.module.module'

    def button_uninstall(self):
        if not self.env.su and 'ir_rule_protected' in self.mapped('name'):
            raise AccessError(self.env._('Only the superuser can uninstall protected access rules.'))
        return super().button_uninstall()
