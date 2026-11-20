# Copyright 2020 Eugene Molotov <https://it-projects.info/team/em230418>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import fields, models
from odoo.exceptions import ValidationError


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _invoice_paid_hook(self):
        result = super()._invoice_paid_hook()
        plans = {
            self.env.ref('saas_product.product_users_monthly').id: 'month',
            self.env.ref('saas_product.product_users_annually').id: 'year',
        }
        invoices = self.filtered(lambda move: move.move_type == 'out_invoice' and move.payment_state == 'paid')
        invoices.lock_for_update(allow_referencing=True)
        for invoice in invoices:
            pending_plans = invoice.invoice_line_ids.filtered(
                lambda line: line.product_id.id in plans and not line.saas_service_applied and not line.contract_line_id
            )
            orders = pending_plans.sale_line_ids.order_id
            for order in orders:
                plan_lines = pending_plans.filtered(lambda line: order in line.sale_line_ids.order_id)
                periods = {plans[line.product_id.id] for line in plan_lines}
                if len(periods) != 1:
                    raise ValidationError(self.env._('Use one subscription period per SaaS order.'))
                build = order.build_id.sudo()
                if not build:
                    continue
                build.lock_for_update(allow_referencing=True)
                build.invalidate_recordset(['contract_id', 'state'])
                if build.contract_id:
                    # Existing subscriptions are billed through their contract.
                    # Do not replace one when a sales invoice is replayed.
                    continue
                if build.state != 'draft':
                    continue
                period = periods.pop()
                quantity = sum(plan_lines.mapped('quantity'))
                if quantity < 1 or quantity != int(quantity):
                    raise ValidationError(self.env._('The SaaS user quantity must be a positive whole number.'))
                lines = invoice.invoice_line_ids.filtered(
                    lambda line: order in line.sale_line_ids.order_id and line.product_id.product_tmpl_id.is_saas_product
                )
                contract_lines = [{
                    'name': line.name,
                    'product_id': line.product_id.id,
                    'price_unit': line.price_unit,
                    'quantity': line.quantity,
                    'uom_id': line.product_uom_id.id,
                } for line in lines]
                expiration_date = fields.Datetime.now() + plan_lines[0].product_id._get_expiration_timedelta()
                # The paid invoice and its sales order identify this one build.
                # Provisioning runs with operator rights, never request values.
                contract = self.env['contract.contract'].sudo().with_context(create_build_vals={
                    'expiration_date': expiration_date, 'max_users_limit': int(quantity),
                }).create({
                    'name': self.env._("%s's SaaS Contract", order.partner_id.name),
                    'partner_id': order.partner_id.id,
                    'company_id': order.company_id.id,
                    'contract_line_fixed_ids': [(0, 0, vals) for vals in contract_lines],
                    'line_recurrence': False,
                    'build_id': build.id,
                    'recurring_rule_type': period + 'ly',
                    'recurring_interval': 1,
                })
                # OCA checks whether recurrence is changing on a contract
                # that already has invoices, so link the paid lines after creation.
                for contract_line, invoice_line in zip(contract.contract_line_ids.sorted('id'), lines, strict=True):
                    contract_line._link_saas_invoice_line(invoice_line.sudo())
                plan_lines.sudo().write({'saas_service_applied': True})
        return result
