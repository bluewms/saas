# Copyright 2018 Ivan Yelizariev <https://it-projects.info/team/yelizariev>
# License MIT (https://opensource.org/licenses/MIT).
from urllib.parse import urlencode, urlsplit, urlunsplit

import requests
from werkzeug.exceptions import Forbidden, ServiceUnavailable

from odoo import http
from odoo.exceptions import AccessDenied
from odoo.http import request
from odoo.http.session import authenticate
from odoo.tools import consteq

from odoo.addons.web.controllers.utils import _get_login_redirect_url

from ..models.res_users import VERIFIED_LOGIN


class AuthQuick(http.Controller):

    def _master_endpoint(self, path):
        # The caller can select neither the issuer nor the tenant reference.
        config = request.env['ir.config_parameter'].sudo()
        try:
            master = urlsplit(config.get_str('auth_quick.master', ''))
            master.port
        except ValueError:
            raise ServiceUnavailable() from None
        if master.scheme not in ('http', 'https') or not master.hostname or master.username or master.password:
            raise ServiceUnavailable()
        return urlunsplit((master.scheme, master.netloc, path, '', ''))

    @http.route('/auth_quick/login', type='http', auth='public', methods=['GET'])
    def login(self, build_login=None, build_user_id=None):
        config = request.env['ir.config_parameter'].sudo()
        build = config.get_str('auth_quick.build', '')
        if not build or not (build_login or build_user_id):
            raise Forbidden()
        params = {'build': build, 'build_url': request.httprequest.url_root}
        if build_login:
            params['build_login'] = build_login
        if build_user_id:
            params['build_user_id'] = build_user_id
        return request.redirect(
            self._master_endpoint('/auth_quick_master/get-token') + '?' + urlencode(params),
            local=False,
        )

    @http.route('/auth_quick/check-token', type='http', auth='public', methods=['GET', 'POST'])
    def check_token(self, token=None):
        if not isinstance(token, str) or not 1 <= len(token) <= 128:
            raise Forbidden()
        headers = {'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'}
        if request.httprequest.method == 'GET':
            response = request.render('auth_quick.confirm_login', {'token': token})
            response.headers.extend(headers)
            return response

        user = self._verify_token(token)
        credential = {'login': user.login, 'type': 'auth_quick', 'proof': VERIFIED_LOGIN, 'uid': user.id}
        try:
            auth_info = authenticate(request.session, request.env, credential)
        except AccessDenied:
            raise Forbidden() from None
        response = request.redirect(_get_login_redirect_url(auth_info['uid']), code=303)
        response.headers.extend(headers)
        return response

    def _verify_token(self, token):
        build = request.env['ir.config_parameter'].sudo().get_str('auth_quick.build', '')
        if not build:
            raise Forbidden()
        url = self._master_endpoint('/auth_quick_master/check-token')
        payload = {'jsonrpc': '2.0', 'method': 'call', 'id': 1, 'params': {'token': token, 'build': build}}
        try:
            response = requests.post(url, json=payload, timeout=(3, 10), allow_redirects=False)
            response.raise_for_status()
            if response.status_code != 200:
                raise ServiceUnavailable()
            payload = response.json()
        except (requests.RequestException, ValueError):
            raise ServiceUnavailable() from None

        result = payload.get('result') if isinstance(payload, dict) else None
        data = result.get('data') if isinstance(result, dict) and result.get('success') == 'ok' else None
        audience = data.get('build') if isinstance(data, dict) else None
        if not isinstance(audience, str) or not consteq(audience.encode(), build.encode()):
            raise Forbidden()

        user_id = data.get('build_user_id')
        login = data.get('build_login')
        users = request.env['res.users'].sudo()
        if type(user_id) is int and user_id > 0:
            user = users.browse(user_id).exists()
        elif isinstance(login, str) and login:
            user = users.search([('login', '=', login)], limit=1)
        else:
            raise Forbidden()
        if not user or not user.active:
            raise Forbidden()
        return user
