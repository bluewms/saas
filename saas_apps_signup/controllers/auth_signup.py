# Copyright 2020 Eugene Molotov <https://it-projects.info/team/em230418>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo.http import request
from odoo.exceptions import ValidationError
from odoo.addons.auth_signup_verify_email.controllers.main import SignupVerifyEmail
import logging

from ..exceptions import OperatorNotAvailable


try_now_args = ("installing_modules", "max_users_limit", "period")
EXTRA_SIGN_UP_REQUEST_PARAMS = try_now_args + (
    # signup form values
    "company_name",
    "database_name",
    "phone",
    "database_lang",
    "country_code",

    "saas_template_id",
    "sale_order_id",
    "operator_id",
)
_logger = logging.getLogger(__name__)


class Main(SignupVerifyEmail):
    def get_auth_signup_qcontext(self):
        d = {k: v for (k, v) in request.params.items() if k in EXTRA_SIGN_UP_REQUEST_PARAMS}
        d.update(super(Main, self).get_auth_signup_qcontext())

        if any(d.get(key) for key in try_now_args):
            # "Try now" is pressed
            try:
                valid = (
                    d['period'] in ('year', 'month') and int(d['max_users_limit']) > 0
                    and bool(d.get('installing_modules') or d.get('saas_template_id'))
                    and not (d.get('installing_modules') and d.get('saas_template_id'))
                    and not d.get('sale_order_id')
                )
            except (KeyError, ValueError, TypeError):
                valid = False
            if not valid:
                raise ValidationError(request.env._('Choose a valid trial package, period, and user limit.'))

        elif d.get('sale_order_id'):
            # "Buy now" is pressed
            d["sale_order_id"] = int(d["sale_order_id"])
            if any(d.get(key) for key in try_now_args):
                raise ValidationError(request.env._('A checkout signup cannot also create a trial.'))
            # The cart id comes from the signed server-side session. A submitted
            # order id must never let signup reassign another customer's order.
            cart = request.cart
            if not cart or cart.id != d['sale_order_id'] or cart.state not in ('draft', 'sent'):
                raise ValidationError(request.env._('The signup cart is not available.'))

        if d.get("saas_template_id"):
            template = request.env['saas.template'].sudo().browse(int(d['saas_template_id'])).exists()
            if not template or not template.is_package or not template.product_tmpl_id.website_published:
                raise ValidationError(request.env._('The selected package is not available.'))
        elif d.get("installing_modules"):
            template = request.env.ref("saas_apps.base_template")

        elif d.get("sale_order_id"):
            # Buy now is pressed
            # Detect template from the cart

            order = request.env["sale.order"].sudo().browse(d["sale_order_id"])
            template = request.env["saas.template"].sudo().search([
                ('is_package', '=', True),
                ("product_tmpl_id", "in", order.mapped("order_line.product_id.product_tmpl_id").ids),
            ])
            if not template:
                template = request.env.ref("saas_apps.base_template")
            elif len(template) > 1:
                _logger.warning("More that one saas package in order. Using first one")
                template = template[0]

        else:
            template = None
        if template:
            available = template.sudo().operator_ids.filtered(lambda row: row.state == 'done')
            if d.get('operator_id'):
                try:
                    selected_operator = int(d['operator_id'])
                except (ValueError, TypeError):
                    raise ValidationError(request.env._('Invalid database operator.'))
                if selected_operator not in available.operator_id.ids:
                    raise OperatorNotAvailable(request.env._('The selected operator is not ready for this offer.'))
            else:
                d["operator_id"] = template._random_ready_operator_id()

        d["langs"] = request.env["res.lang"].get_installed()
        d["countries"] = [
            (country.code, country.name)
            for country in request.env["res.country"].sudo().search([], order="name")
            if country.code
        ]
        return d

    def passwordless_signup(self):
        values = request.params
        qcontext = self.get_auth_signup_qcontext()

        database_name = values.get("database_name")
        if database_name:
            db_record = request.env['saas.db'].sudo().search([('name', '=', database_name)], limit=1)
            if db_record:
                qcontext["error"] = "Database %s already exist" % (database_name,)
                return request.render("auth_signup.signup", qcontext)

        try:
            return super(Main, self).passwordless_signup()
        except OperatorNotAvailable as e:
            qcontext["error"] = str(e)
            return request.render("auth_signup.signup", qcontext)
