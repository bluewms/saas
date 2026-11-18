# Copyright 2020 Eugene Molotov <https://it-projects.info/team/em230418>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo.addons.website_sale.controllers.main import WebsiteSale as BaseWebsiteSale
from odoo.http import request, route
from odoo.addons.auth_quick_master.tools.build_redirection import build_confirmation
from werkzeug.exceptions import Forbidden


class WebsiteSale(BaseWebsiteSale):
    @route()
    def shop_checkout(self, try_skip_step=None, **query_params):
        order = request.cart
        if order and order.order_line.product_id.product_tmpl_id.filtered('is_saas_product'):
            if request.env.user._is_public():
                return request.redirect('/web/signup?sale_order_id={}'.format(order.id))
            if not order.build_id:
                build = self._get_checkout_build()
                if not build:
                    return request.redirect('/my/builds/create?redirect=/shop/checkout')
                return build_confirmation(
                    '/saas_apps_signup/prepare_checkout', {}, request.csrf_token(),
                    request.env._('Confirm the SaaS database for checkout'),
                )
        return super().shop_checkout(try_skip_step=try_skip_step, **query_params)

    def _get_checkout_build(self):
        return request.env['saas.db'].search([
            ('type', '=', 'build'), ('state', '=', 'draft'),
            ('admin_user', '=', request.env.user.id), ('contract_id', '=', False),
        ], order='id DESC', limit=1)

    @route('/saas_apps_signup/prepare_checkout', type='http', auth='user', website=True, methods=['POST'])
    def prepare_checkout(self, **kwargs):
        order = request.cart
        if not order:
            return request.redirect('/shop/cart')
        if order.partner_id.commercial_partner_id != request.env.user.partner_id.commercial_partner_id:
            raise Forbidden()
        order._check_not_partially_paid()
        build = self._get_checkout_build()
        if not build:
            return request.redirect('/my/builds/create?redirect=/shop/checkout')
        order.build_id = build
        return request.redirect('/shop/checkout')
