# Copyright 2020 Vildan Safin <https://www.it-projects.info/team/Enigma228322>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo.http import route, request, Controller
from odoo.exceptions import ValidationError
from odoo.addons.website_sale.controllers.main import WebsiteSale


class SaaSAppsController(Controller):
    @route("/price", type="http", auth="public", website=True)
    def user_page(self, **kw):
        res = request.env["res.config.settings"].sudo().default_get(
            [
                "show_packages",
                "show_apps",
                "show_buy_now_button",
                "show_try_trial_button",
            ]
        )
        show_apps = bool(res["show_apps"])
        show_packages = bool(res["show_packages"])

        apps = (
            request.env["saas.app"].sudo().search([("allow_to_sell", "=", True)])
            if show_apps
            else []
        )
        packages = (
            request.env["saas.template"].sudo().search([("is_package", "=", True)])
            if show_packages
            else []
        )
        return request.render(
            "saas_apps.price",
            {
                "apps": apps,
                "packages": packages,
                "show_apps": show_apps,
                "show_packages": show_packages,
                "show_buy_now_button": bool(res["show_buy_now_button"]),
                "show_try_trial_button": bool(res["show_try_trial_button"]),
                "currency": request.env.website.currency_id,
                "user_month_product": request.env.ref(
                    "saas_product.product_users_monthly"
                ),
                "user_year_product": request.env.ref(
                    "saas_product.product_users_annually"
                ),
            },
        )

    @route(["/check_saas_template"], type="jsonrpc", auth="public")
    def check_saas_template(self, **kw):
        # TODO: надо бы ошибки выводить
        # TODO: если указанный template_id не найден, то не надо использовать базовый шаблон
        template_id = kw.get("template_id")
        templates = request.env["saas.template"].sudo()

        # If package exist, use package saas_template
        template = templates.search(
            [("is_package", "=", True), ("id", "=", template_id)]
        )
        if not template:
            # If package wasn't selected, use base saas_template
            template = templates.env.ref("saas_apps.base_template")

        if not template.operator_ids.random_ready_operator():
            return {"id": template.id, "state": "creating"}
        return {"id": template.id, "state": "ready"}


# TODO: он нужен?
class SaasAppsCart(WebsiteSale):
    def clear_cart(self):
        order = request.cart
        if order:
            for line in order.website_order_line:
                line.unlink()

    @route(
        "/price/cart/update_json",
        type="jsonrpc",
        auth="public",
        methods=["POST"],
        website=True,
        csrf=False,
    )
    def cart_update_price_page(self, **kw):
        period = kw.get("period")
        # Adding user as product in cart
        if period == "month":
            user_product = request.env.ref("saas_product.product_users_monthly")
        elif period == "year":
            user_product = request.env.ref("saas_product.product_users_annually")
        else:
            raise ValidationError(request.env._('Choose a monthly or yearly subscription.'))

        try:
            user_cnt = int(kw.get('user_cnt'))
            product_ids = {int(value) for value in kw.get('product_ids', [])}
        except (TypeError, ValueError):
            raise ValidationError(request.env._('Choose a valid user quantity and product selection.'))
        if not 1 <= user_cnt <= 2147483647:
            raise ValidationError(request.env._('The user quantity must be a positive whole number.'))
        apps = request.env['saas.app'].sudo().search([('allow_to_sell', '=', True)])
        packages = request.env['saas.template'].sudo().search([
            ('is_package', '=', True), ('product_tmpl_id.website_published', '=', True),
        ])
        allowed = apps.mapped(period + '_product_id') | packages.mapped(period + '_product_id')
        allowed = allowed.filtered(lambda product: not product.company_id or product.company_id == request.env.website.company_id)
        if product_ids - set(allowed.ids):
            raise ValidationError(request.env._('One or more selected products are not available for this subscription period.'))
        if len(product_ids & set(packages.mapped(period + '_product_id').ids)) > 1:
            raise ValidationError(request.env._('Choose one SaaS package per order.'))
        self.clear_cart()
        sale_order = request.cart or request.env.website._create_cart()
        sale_order.with_context(skip_cart_verification=True)._cart_add(
            product_id=int(user_product.id), quantity=user_cnt
        )

        for product_id in sorted(product_ids):
            sale_order.with_context(skip_cart_verification=True)._cart_add(
                product_id=int(product_id), quantity=1
            )
        return {"link": "/shop/cart"}

    @route()
    def shop(self, **post):
        return request.redirect("/price")
