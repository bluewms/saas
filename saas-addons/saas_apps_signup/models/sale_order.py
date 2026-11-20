# Copyright 2020 Eugene Molotov <https://it-projects.info/team/em230418>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SaleOrder(models.Model):

    _inherit = 'sale.order'

    build_id = fields.Many2one("saas.db", copy=False)

    @api.constrains('build_id', 'partner_id')
    def _check_build_partner(self):
        for order in self:
            if order.build_id and (
                order.build_id.type != 'build'
                or not order.build_id.admin_user
                or order.build_id.admin_user.partner_id.commercial_partner_id != order.partner_id.commercial_partner_id
            ):
                raise ValidationError(self.env._('The selected build does not belong to this customer.'))

    def _is_cart_ready_for_payment(self):
        self.ensure_one()
        if self.order_line.product_id.product_tmpl_id.filtered('is_saas_product') and not self.build_id:
            self._add_blocking_alert(self.env._('Choose a SaaS database from checkout before paying.'))
            return False
        return super()._is_cart_ready_for_payment()
