# Copyright 2020 Eugene Molotov <https://it-projects.info/team/em230418>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import ValidationError


_SAAS_SIGNUP_OPTIONS = {
    'database_name', 'operator_id', 'sale_order_id', 'period', 'max_users_limit',
    'installing_modules', 'saas_template_id',
}


class ResUsers(models.Model):
    _inherit = 'res.users'

    database_lang = fields.Char("Preferred language for database")
    saas_pending_signup = fields.Json(groups='base.group_system', copy=False)

    @api.private
    @api.model
    def signup(self, values, token=None):
        # Only accept profile data and the options prepared by the signup flow.
        allowed = {
            'name', 'login', 'password', 'email', 'lang', 'phone', 'company_name',
            'country_code', 'country_id', 'database_lang',
        } | _SAAS_SIGNUP_OPTIONS
        values = {key: value for key, value in values.items() if key in allowed}
        options = {key: values.pop(key) for key in _SAAS_SIGNUP_OPTIONS if key in values}
        if not (options.get('sale_order_id') or options.get('period')):
            options = {}
        company_name = (values.pop('company_name', None) or '').strip()
        if company_name:
            options['company_name'] = company_name
        self = self.with_user(SUPERUSER_ID)
        if not token and not self.env.website and not self.env.context.get('host_id'):
            self = self.with_context(host_id=self.env.ref('base.default_website').id)

        if country_code := values.pop('country_code', None):
            values['country_id'] = self.env['res.country'].search([('code', '=', country_code)], limit=1).id

        if token:
            # Keep token consumption and the start of provisioning atomic. The
            # reset controller renders some business errors and can commit.
            with self.env.cr.savepoint():
                result = super().signup(values, token)
                login, _password = result
                user = self.search([('login', '=', login)], limit=1)
                if user.saas_pending_signup:
                    user._complete_saas_signup()
                return result

        if self.env.context.get('create_user') and options:
            if options.get('sale_order_id'):
                cart = self.env['sale.order'].browse(int(options['sale_order_id'])).exists()
                if not cart or cart.state not in ('draft', 'sent') or cart.build_id:
                    raise ValidationError(self.env._('The signup cart is not available.'))
                options['cart_partner_id'] = cart.partner_id.id
            values['saas_pending_signup'] = options

        return super().signup(values, token)

    def _complete_saas_signup(self):
        self.ensure_one()
        options = self.saas_pending_signup
        database_name = options.get('database_name')
        cart = self.env['sale.order']
        if cart_id := options.get('sale_order_id'):
            cart = cart.browse(int(cart_id)).exists()
            if (
                not cart or cart.state not in ('draft', 'sent') or cart.build_id
                or cart.partner_id.id != options.get('cart_partner_id')
            ):
                raise ValidationError(self.env._('The signup cart is not available.'))

        if options.get('company_name') and not self.partner_id.parent_id:
            self.partner_id.parent_id = self.env['res.partner'].create({
                'name': options['company_name'], 'is_company': True,
                'country_id': self.partner_id.country_id.id,
            })

        if database_name or cart:
            build = self.env['saas.db'].create({
                'name': database_name,
                'operator_id': int(options['operator_id']),
                'admin_user': self.id,
            })
            if cart:
                cart.write({'partner_id': self.partner_id.id, 'build_id': build.id})
            else:
                self.env['contract.contract']._create_saas_contract_for_trial(
                    build, int(options.get('max_users_limit') or 1), options['period'],
                    installing_modules=(options.get('installing_modules') or '').split(','),
                    saas_template_id=options.get('saas_template_id'),
                )
        self.saas_pending_signup = False
