# Copyright 2020 Eugene Molotov <https://it-projects.info/team/em230418>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

import logging

from dateutil.relativedelta import relativedelta

from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import ValidationError

from ..exceptions import OperatorNotAvailable

_logger = logging.getLogger(__name__)


class Contract(models.Model):

    _inherit = 'contract.contract'

    @api.model_create_multi
    def create(self, vals_list):
        records = super(Contract, self).create(vals_list)

        create_build_vals = self.env.context.get("create_build_vals")
        if create_build_vals:
            for record in records:
                record.env['saas.db']._check_management_access()
                # Use the server user for trusted elevated provisioning, only
                # after the caller's management check has succeeded.
                worker_record = record.with_user(SUPERUSER_ID) if record.env.su else record
                worker_record.with_delay()._create_build(dict(create_build_vals))

        return records

    @api.model
    def _create_saas_contract_for_trial(self, build, max_users_limit, subscription_period, installing_modules=None, saas_template_id=None):
        build.ensure_one()
        build.check_access('read')
        build.lock_for_update(allow_referencing=True)
        build.invalidate_recordset(['contract_id', 'state'])
        if build.type != 'build' or build.state != 'draft' or build.contract_id or not build.admin_user:
            raise ValidationError(self.env._('Select an unassigned draft tenant database.'))
        try:
            max_users_limit = int(max_users_limit)
        except (TypeError, ValueError):
            raise ValidationError(self.env._('The user limit must be a positive whole number.'))
        if max_users_limit < 1:
            raise ValidationError(self.env._('The user limit must be a positive whole number.'))
        installing_modules = sorted({name.strip() for name in (installing_modules or []) if name.strip()})
        if bool(installing_modules) == bool(saas_template_id):
            raise ValidationError(self.env._('Choose apps or one package.'))
        apps = self.env['saas.app'].search([('name', 'in', installing_modules), ('allow_to_sell', '=', True)])
        if set(apps.mapped('name')) != set(installing_modules):
            raise ValidationError(self.env._('One or more selected apps are not available for sale.'))
        if saas_template_id:
            template = self.env['saas.template'].browse(int(saas_template_id)).exists()
            if not template or not template.is_package or not template.product_tmpl_id.website_published:
                raise ValidationError(self.env._('The selected package is not available for sale.'))
        else:
            template = self.env.ref('saas_apps.base_template')
        if not template.operator_ids.filtered(lambda row: row.state == 'done' and row.operator_id == build.operator_id):
            raise OperatorNotAvailable(self.env._('No ready deployment is available on the selected operator.'))
        partner = build.admin_user.partner_id
        contract_lines = []
        contract_vals = {}
        subscription_period_suffix = ""
        if subscription_period == "month":
            subscription_period_suffix = "monthly"
        elif subscription_period == "year":
            subscription_period_suffix = "annually"
        else:
            raise ValidationError(self.env._('Choose a monthly or yearly subscription.'))

        expiration_date = fields.Datetime.now() + relativedelta(months=1)
        product_users = self.env.ref("saas_product.product_users_{}".format(subscription_period_suffix))

        contract_vals = {
            "name": "{}'s SaaS Contract".format(partner.name),
            "build_id": build.id,
            "partner_id": partner.id,
            "line_recurrence": False,
            "trial_expiration_date": expiration_date,
            "date_start": fields.Date.to_date(expiration_date),
            "recurring_rule_type": subscription_period + "ly",
            "recurring_interval": 1,
        }

        contract_lines += product_users.mapped(lambda p: {
            "name": p.name,
            "product_id": p.id,
            "price_unit": p.lst_price,
            "quantity": max_users_limit,
        })

        if installing_modules:
            contract_lines += apps\
                                  .mapped("{}_product_id".format(subscription_period))\
                                  .mapped(lambda p: {
                                      "name": p.name,
                                      "product_id": p.id,
                                      "price_unit": p.lst_price,
                                      "quantity": 1,
                                  })

        if saas_template_id:
            saas_template_id = int(saas_template_id)
            contract_lines += self.env["saas.template"]\
                                  .browse(saas_template_id)\
                                  .mapped("{}_product_id".format(subscription_period))\
                                  .mapped(lambda p: {
                                      "name": p.name,
                                      "product_id": p.id,
                                      "price_unit": p.lst_price,
                                      "quantity": 1,
                                  })

        for x in contract_lines:
            x.update({
                "uom_id": self.env.ref("uom.product_uom_unit").id,
            })

        contract_vals["contract_line_fixed_ids"] = list(map(lambda line: (0, 0, line), contract_lines))
        return self.env["contract.contract"].with_context(create_build_vals={
            "max_users_limit": max_users_limit,
            "expiration_date": expiration_date,
        }).create(contract_vals)

    @api.model
    def _get_contracts_to_invoice_domain(self, date_ref=None):
        return super()._get_contracts_to_invoice_domain(date_ref) & (
            fields.Domain('trial_expiration_date', '=', False)
            | fields.Domain('trial_expiration_date', '<=', fields.Datetime.now())
        )

    def _create_build(self, build_vals):
        self.env['saas.db']._check_management_access()
        if set(build_vals) - {'expiration_date', 'max_users_limit', 'database_limit_size'}:
            raise ValidationError(self.env._('Unsupported build provisioning values.'))
        for contract in self:
            partner = contract.partner_id
            build = contract.build_id
            if build:
                if build.state == 'done' and build.contract_id == contract:
                    continue
                if build.state != 'draft' or not build.admin_user or build.admin_user.partner_id.commercial_partner_id != partner.commercial_partner_id:
                    raise ValidationError(self.env._('The draft build does not belong to the contract customer.'))
            else:
                # TODO: избавиться от этой фигни
                build = self.env["saas.db"].search([
                    ("type", "=", "build"),
                    ("state", "=", "draft"),
                    ("admin_user", "in", partner.user_ids.ids),
                ], order='id DESC', limit=1)

            if not build:
                _logger.warning("No draft build found for making contract")
                continue

            contract_products = contract.contract_line_ids.mapped('product_id')
            contract_product_templates = contract_products.mapped('product_tmpl_id')

            # fmt: off
            build_installing_modules = self.env['saas.app'].sudo().search([
                ("product_tmpl_id", "in", contract_product_templates.ids)
            ]).mapped("name")
            # fmt: on

            # TODO: оператор должен определяет по билду!
            template = self.env["saas.template"].search([
                ("is_package", "=", True),
                ("product_tmpl_id", "in", contract_product_templates.ids),
            ])
            if not template:
                template = self.env.ref("saas_apps.base_template")
            elif len(template) > 1:
                _logger.warning("Expected only one template. Using first one from {} (given using {})".format(
                    repr(template),
                    repr(template.mapped("product_tmpl_id")),
                ))
                template = template[0]
            template_operators = template.operator_ids.filtered(lambda row: row.operator_id == build.operator_id)
            if not template_operators:
                raise OperatorNotAvailable("No template operators in base template. Contact administrator")

            template_operator = template_operators.random_ready_operator()
            if not template_operator:
                raise OperatorNotAvailable("No template operators are ready. Try again later")

            installing_modules_var = repr(list(build_installing_modules))

            build.write(build_vals)

            template_operator.create_db(
                key_values={"installing_modules": installing_modules_var},
                draft_build_id=build.id
            )

            # TODO: это тоже не забудь убрать
            if not contract.build_id:
                contract.build_id = build

    @api.model
    def _finalize_and_create_invoices(self, invoices_values):
        invoices = super(Contract, self)._finalize_and_create_invoices(invoices_values)
        for invoice in invoices:
            contract = invoice.contract_id
            build = contract.build_id

            contract.invalidate_recordset()
            if build and build.state == "done":
                invoice.action_post()

        return invoices


class ContractLine(models.Model):

    _inherit = 'contract.line'

    @api.model_create_multi
    def create(self, vals_list):
        move_line_ids = [vals.pop("move_line_id", None) for vals in vals_list]
        records = super(ContractLine, self).create(vals_list)
        for record, move_line_id in zip(records, move_line_ids):
            if move_line_id:
                record._link_saas_invoice_line(self.env['account.move.line'].browse(move_line_id).exists())
        return records

    def _link_saas_invoice_line(self, move_line):
        self.ensure_one()
        move_line.ensure_one()
        move_line.check_access('write')
        if move_line.product_id != self.product_id or move_line.partner_id.commercial_partner_id != self.contract_id.partner_id.commercial_partner_id:
            raise ValidationError(self.env._('The invoice line does not belong to this contract.'))
        if move_line.contract_line_id and move_line.contract_line_id != self:
            raise ValidationError(self.env._('The invoice line is already linked to another contract line.'))
        if move_line.company_id != self.contract_id.company_id:
            raise ValidationError(self.env._('The invoice line and contract must belong to the same company.'))
        move_line.contract_line_id = self
