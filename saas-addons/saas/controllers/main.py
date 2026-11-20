# Copyright 2018 Ivan Yelizariev <https://it-projects.info/team/yelizariev>
# Copyright 2019 Denis Mudarisov <https://it-projects.info/team/trojikman>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from werkzeug.exceptions import Forbidden, NotFound

import odoo
from odoo.http import request, route


class SaasController(odoo.http.Controller):
    @route('/saas/auth-to-build/<int:build_id>', type='http', auth='user')
    def auth_to_build(self, build_id=None, **kwargs):
        if not build_id:
            return False
        build = request.env['saas.db'].browse(build_id).exists()
        if not build or not build.has_access('read'):
            raise NotFound()
        is_owner = 'admin_user' in build._fields and build.admin_user == request.env.user
        if not (request.env.user.has_group('saas.group_manager') or is_owner):
            raise Forbidden()
        if build.type != 'build' or build.state != 'done':
            raise NotFound()
        return request.redirect_query('/auth_quick_master/get-token', {'build': build.id})
