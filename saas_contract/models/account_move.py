# Copyright 2020 Eugene Molotov <https://it-projects.info/team/em230418>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class AccountMove(models.Model):
    _inherit = "account.move"

    saas_service_applied = fields.Boolean(
        'SaaS service applied', compute='_compute_saas_service_applied', groups='base.group_system',
        help='Prevents a payment callback from granting the same service more than once.',
    )

    @api.depends('invoice_line_ids.product_id', 'invoice_line_ids.saas_service_applied')
    def _compute_saas_service_applied(self):
        plans = self.env.ref('saas_product.product_users_monthly') | self.env.ref('saas_product.product_users_annually')
        for invoice in self:
            lines = invoice.invoice_line_ids.filtered(lambda line: line.product_id in plans)
            invoice.saas_service_applied = bool(lines) and all(lines.mapped('saas_service_applied'))

    def _invoice_paid_hook(self):
        result = super()._invoice_paid_hook()
        invoices = self.filtered(lambda move: move.move_type == 'out_invoice' and move.payment_state == 'paid')
        invoices.lock_for_update(allow_referencing=True)
        plans = self.env.ref('saas_product.product_users_monthly') | self.env.ref('saas_product.product_users_annually')
        for invoice in invoices:
            lines = invoice.invoice_line_ids.filtered(lambda line: line.product_id in plans)
            lines.invalidate_recordset(['saas_service_applied'])
            pending = lines.filtered(lambda line: not line.saas_service_applied)
            for linked_build, build_lines in pending.grouped(lambda line: line.contract_line_id.build_id).items():
                # Only a contract linked by the billing flow can grant tenant
                # service; the accounting user need not have provisioning rights.
                build = linked_build.sudo()
                if not build:
                    continue
                products = build_lines.product_id
                if len(products) != 1:
                    raise ValidationError(self.env._('Use one subscription period per build on a SaaS invoice.'))
                build.lock_for_update(allow_referencing=True)
                build.invalidate_recordset(['expiration_date'])
                now = fields.Datetime.now()
                start = max(now, build.expiration_date or now)
                build.expiration_date = start + products._get_expiration_timedelta()
                build_lines.sudo().write({'saas_service_applied': True})
        return result

    @api.private
    def action_invoice_paid(self):
        # Keep the old Python entry point for extensions while Odoo 20 calls
        # _invoice_paid_hook directly.
        return self._invoice_paid_hook()
