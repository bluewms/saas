# Copyright 2020 Eugene Molotov <https://it-projects.info/team/em230418>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

import logging
from urllib.parse import parse_qs, urlsplit

import werkzeug
from werkzeug.urls import url_encode

from odoo import SUPERUSER_ID, fields
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError
from odoo.http import Controller, request, route
from odoo.addons.auth_quick_master.tools.build_redirection import build_confirmation
from odoo.addons.saas_portal.controllers.portal import CustomerPortal

from ..exceptions import OperatorNotAvailable

_logger = logging.getLogger(__name__)


def _url_with_query(url, params):
    return "{}?{}".format(url, url_encode(params))


def _local_redirect(url):
    if isinstance(url, str) and url.startswith('/') and not url.startswith('//') and '\\' not in url and not any(ord(char) < 32 for char in url):
        return url
    return '/my/builds'


class Main(Controller):
    def _available_operator(self, operator_id):
        try:
            operator_id = int(operator_id)
        except (TypeError, ValueError):
            return request.env['saas.operator']
        base_template = request.env.ref('saas_apps.base_template')
        # The public selector exposes only operators with a ready, published
        # offer. Arbitrary infrastructure records are never returned.
        deployments = request.env['saas.template.operator'].sudo().search([
            ('operator_id', '=', operator_id), ('state', '=', 'done'),
        ])
        deployments = deployments.filtered(
            lambda row: row.template_id == base_template
            or (row.template_id.is_package and row.template_id.product_tmpl_id.website_published)
        )
        return deployments.operator_id[:1]

    @route("/saas_apps_signup/is_database_slot_available", auth="public", type="jsonrpc", methods=['POST'])
    def is_available(self, database_name, operator_id, **kw):
        operator = self._available_operator(operator_id)
        if not operator:
            return {'answer': request.env._('No ready operator is available.')}
        try:
            slot = request.env['saas.db'].sudo()._get_website_build_slot(operator, database_name)
        except ValidationError as error:
            return {'answer': str(error)}
        return {'domain': slot['domain'], 'database_name': slot['database_name']}

    @route("/my/builds/create", auth="user", type="http", website=True, methods=['GET', 'POST'])
    def portal_build_selector(self, database_name=None, redirect=None, operator_id=None, **kw):
        redirect = _local_redirect(redirect)
        qcontext = {'error': False, 'operator_id': False}
        if request.httprequest.method == 'POST':
            try:
                operator = self._available_operator(operator_id)
                if not operator:
                    raise OperatorNotAvailable(request.env._('No ready operator is available.'))
                user = request.env.user
                user.lock_for_update(allow_referencing=True)
                Build = request.env['saas.db'].sudo()
                if not user.has_group('saas.group_manager') and Build.search_count([
                    ('state', '=', 'draft'), ('type', '=', 'build'), ('admin_user', '=', user.id),
                ]):
                    raise ValidationError(request.env._('You already have a draft database.'))
                with request.env.cr.savepoint():
                    Build._create_website_build_draft(user, operator, database_name)
                return request.redirect(redirect)
            except (UserError, ValueError, TypeError) as error:
                qcontext['error'] = str(error)
        else:
            template = request.env.ref('saas_apps.base_template').sudo()
            template_ids = parse_qs(urlsplit(redirect).query).get('saas_template_id', [])
            if template_ids:
                try:
                    package = request.env['saas.template'].sudo().browse(int(template_ids[0])).exists()
                except ValueError:
                    package = request.env['saas.template']
                if package and package.is_package and package.product_tmpl_id.website_published:
                    template = package
            try:
                qcontext['operator_id'] = template._random_ready_operator_id()
            except OperatorNotAvailable as error:
                qcontext['error'] = str(error)
        qcontext.update(
            query=url_encode({'redirect': redirect}),
            database_name=database_name or '',
            operator_id=operator_id or qcontext['operator_id'],
        )
        return request.render('saas_apps_signup.portal_create_build', qcontext)

    @route("/saas_apps_signup/make_database_for_trial", auth="public", type="http", website=True, methods=['GET', 'POST'])
    def make_database_for_trial(self, period=None, max_users_limit=None, database_name=None, installing_modules=None, saas_template_id=None, **kw):
        try:
            max_users_limit = int(max_users_limit)
        except (ValueError, TypeError):
            raise werkzeug.exceptions.BadRequest('Invalid user limit')
        if max_users_limit < 1 or period not in ('month', 'year') or (saas_template_id and installing_modules):
            raise werkzeug.exceptions.BadRequest('Invalid trial selection')
        params = {
            'max_users_limit': max_users_limit, 'period': period,
            'installing_modules': installing_modules or '', 'saas_template_id': saas_template_id or '',
        }
        if request.env.user._is_public():
            return request.redirect(_url_with_query('/web/signup', params))
        build = request.env['saas.db'].search([
            ('type', '=', 'build'), ('state', '=', 'draft'), ('admin_user', '=', request.env.user.id),
        ], order='id DESC', limit=1)
        if not build:
            return request.redirect(_url_with_query('/my/builds/create', {
                'redirect': _url_with_query(request.httprequest.path, params),
            }))
        if request.httprequest.method == 'GET':
            return build_confirmation(
                request.httprequest.path, params, request.csrf_token(),
                request.env._('Create the trial database'),
            )
        # Ownership was checked above. The private contract method validates the
        # offer, user limit, and operator before this one privileged operation.
        request.env['contract.contract'].with_user(SUPERUSER_ID)._create_saas_contract_for_trial(
            build, max_users_limit, period,
            installing_modules=(installing_modules or '').split(','),
            saas_template_id=saas_template_id,
        )
        return request.redirect('/my/build/{}'.format(build.id))


class CustomerPortal(CustomerPortal):
    @route(["/my/build/<int:build_id>/renew_subscription"], type="http", auth="user", website=True, methods=['GET', 'POST'])
    def portal_my_build_renew_subscription(self, build_id=None, access_token=None, **kw):
        try:
            build = self._get_owned_build(build_id)
        except (AccessError, MissingError):
            return request.redirect('/my/builds')
        if not build.contract_id:
            return request.not_found()
        contract = build.contract_id
        if contract.trial_expiration_date and contract.trial_expiration_date > fields.Datetime.now():
            return request.redirect('/my/build/{}'.format(build.id))
        if request.httprequest.method == 'GET':
            return build_confirmation(
                request.httprequest.path, {}, request.csrf_token(),
                request.env._('Renew the subscription'),
            )
        if not build.try_lock_for_update(allow_referencing=True):
            return request.redirect('/my/build/{}'.format(build.id))
        if not contract.try_lock_for_update(allow_referencing=True):
            return request.redirect('/my/build/{}'.format(build.id))
        invoices = contract._get_related_invoices().filtered(
            lambda invoice: invoice.state == 'posted' and invoice.payment_state not in ('paid', 'reversed')
        )
        if invoices:
            invoice = invoices[:1]
        else:
            invoice = contract.recurring_create_invoice()
            if not invoice:
                return request.redirect('/my/build/{}'.format(build.id))
            invoice.action_post()
            invoice = invoice[:1]
        return request.redirect(invoice.get_portal_url())
