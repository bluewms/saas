# Copyright 2020 Eugene Molotov <https://it-projects.info/team/em230418>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import api, fields, models, SUPERUSER_ID
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):

    _inherit = 'res.users'

    database_lang = fields.Char("Preferred language for database")

    @api.private
    @api.model
    def signup(self, values, *args, **kwargs):
        # HTTP signup prepares these values. Group/company administration must
        # never be accepted by the elevated signup implementation.
        allowed = {
            'name', 'login', 'password', 'email', 'lang', 'phone', 'company_name',
            'country_code', 'country_id', 'database_lang', 'database_name',
            'operator_id', 'sale_order_id', 'period', 'max_users_limit',
            'installing_modules', 'saas_template_id',
        }
        values = {key: value for key, value in values.items() if key in allowed}
        for key in ('operator_id', 'sale_order_id', 'period', 'max_users_limit', 'installing_modules', 'saas_template_id'):
            if values.get(key) in ('', None):
                values.pop(key, None)
        self = self.with_user(SUPERUSER_ID)

        if values.get("country_code"):
            values["country_id"] = self.env["res.country"].search([("code", "=", values["country_code"])]).id
            del values["country_code"]

        if not self.env.context.get("create_user"):
            return super(ResUsers, self).signup(values, *args, **kwargs)

        elif values.get('sale_order_id'):
            return self.signup_to_buy(values, *args, **kwargs)

        elif values.get('period'):
            return self.signup_to_try(values, *args, **kwargs)

        else:
            return super(ResUsers, self).signup(values, *args, **kwargs)

    @api.private
    def signup_to_try(self, values, *args, **kwargs):
        # popping out values before creating user
        database_name = values.pop("database_name", None)
        installing_modules = values.pop("installing_modules", "").split(",")
        saas_template_id = values.pop("saas_template_id", "")
        max_users_limit = int(values.pop("max_users_limit", 1))
        subscription_period = values.pop("period", "")
        operator_id = int(values.pop("operator_id"))

        res = super(ResUsers, self).signup(values, *args, **kwargs)

        if database_name:
            admin_user = self.env['res.users'].search([('login', '=', res[0])], limit=1)

            build = self.env["saas.db"].create({
                "name": database_name,
                "operator_id": operator_id,
                "admin_user": admin_user.id,
            })

            self.env["contract.contract"]._create_saas_contract_for_trial(
                build, max_users_limit, subscription_period,
                installing_modules=installing_modules,
                saas_template_id=saas_template_id,
            )
        return res

    @api.private
    def signup_to_buy(self, values, *args, **kwargs):
        sale_order = self.env["sale.order"].browse(int(values.pop("sale_order_id")))
        if not sale_order.exists() or sale_order.state not in ('draft', 'sent'):
            raise ValidationError(self.env._('The signup cart is not available.'))

        database_name = values.pop("database_name", None)
        operator_id = int(values.pop("operator_id"))

        res = super(ResUsers, self).signup(values, *args, **kwargs)
        admin_user = self.env['res.users'].search([('login', '=', res[0])], limit=1)
        sale_order.partner_id = admin_user.partner_id

        build = self.env["saas.db"].create({
            "name": database_name,
            "operator_id": operator_id,
            "admin_user": admin_user.id,
        })

        sale_order.write({
            "partner_id": admin_user.partner_id.id,
            "build_id": build.id
        })

        return res
