# Copyright 2018 Ivan Yelizariev <https://it-projects.info/team/yelizariev>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import werkzeug
import urllib.parse
import logging

from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError

from ..tools.build_redirection import build_confirmation

_logger = logging.getLogger(__name__)


class AuthQuickMaster(http.Controller):

    @http.route('/auth_quick_master/get-token', type="http", auth='user', methods=['GET', 'POST'])
    def get_token(self, build=None, build_user_id=None, build_login=None, build_url=None, **kw):
        if request.httprequest.method == 'GET':
            return build_confirmation(
                request.httprequest.path,
                {'build': build, 'build_user_id': build_user_id, 'build_login': build_login, 'build_url': build_url},
                request.csrf_token(),
                request.env._('Continue to the tenant database'),
            )

        try:
            vals = request.env['auth_quick_master.token']._prepare_token_values(build, build_user_id, build_login)
        except (AccessError, TypeError, ValueError):
            raise werkzeug.exceptions.Forbidden()

        # Input and tenant access have been checked with the caller's rights.
        token_obj = request.env['auth_quick_master.token'].sudo().create(vals)

        build_url = token_obj.get_build_url() or build_url

        if not build_url:
            token_obj.unlink()
            return """{"error": "Build url is unknown"}"""

        parsed = urllib.parse.urlsplit(build_url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            token_obj.unlink()
            raise werkzeug.exceptions.BadRequest('Invalid build URL')

        url = urllib.parse.urljoin(build_url, '/auth_quick/check-token?token=%s' % token_obj.token)
        response = werkzeug.utils.redirect(url, 302)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @http.route('/auth_quick_master/check-token', type="jsonrpc", auth='public', methods=['POST'])
    def check_token(self, token, build=None):
        if not isinstance(token, str) or not token or len(token) > 128:
            return {'error': 'Invalid token'}
        # The public endpoint looks up one opaque token and never exposes the
        # token table. Locking prevents two requests from consuming it together.
        token_obj = request.env['auth_quick_master.token'].sudo().search([
            ('token', '=', token)
        ], limit=1).try_lock_for_update(allow_referencing=True)
        if not token_obj:
            return {'error': 'Invalid token'}
        if not token_obj._check_build_reference(build):
            return {'error': 'Invalid build reference'}
        if token_obj.is_obsolete():
            token_obj.unlink()
            return {"error": "Token is obsolete"}

        if not token_obj.user_has_access():
            token_obj.unlink()
            return {"error": "User doesn't have access"}

        result = {"success": "ok", "data": {
            "build_user_id": token_obj.build_user_id,
            "build_login": token_obj.build_login,
            'build': token_obj.build,
        }}
        token_obj.unlink()
        return result
