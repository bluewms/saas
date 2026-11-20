# Copyright 2018 Ivan Yelizariev <https://it-projects.info/team/yelizariev>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo import models, api
from odoo.exceptions import AccessError
from ..tools import check_management_database


class Token(models.Model):
    _inherit = 'auth_quick_master.token'

    def _check_build_reference(self, build):
        self.ensure_one()
        # The client must send its server-side auth_quick.build value. Never
        # accept a token without an audience in a multi-tenant SaaS deployment.
        return build is not None and str(build) == self.build

    def _get_authorized_build(self):
        self.ensure_one()
        try:
            check_management_database(self.env)
        except AccessError:
            return self.env['saas.db']
        try:
            build_id = int(self.build)
        except (TypeError, ValueError):
            return self.env['saas.db']
        build = self.env['saas.db'].with_user(self.user_id).browse(build_id).exists()
        if not build or not build.has_access('read'):
            return self.env['saas.db']
        is_owner = 'admin_user' in build._fields and build.admin_user == self.user_id
        if not self.user_id.active or not (self.user_id.has_group('saas.group_manager') or is_owner):
            return self.env['saas.db']
        return build if build.type == 'build' and build.state == 'done' else self.env['saas.db']

    def _prepare_token_values(self, build, build_user_id=None, build_login=None):
        check_management_database(self.env)
        try:
            build_id = int(build)
        except (TypeError, ValueError):
            raise AccessError(self.env._('Invalid tenant database.'))
        tenant = self.env['saas.db'].browse(build_id).exists()
        if not tenant or not tenant.has_access('read'):
            raise AccessError(self.env._('You do not have access to this tenant database.'))
        is_owner = 'admin_user' in tenant._fields and tenant.admin_user == self.env.user
        if not self.env.user.active or not (self.env.user.has_group('saas.group_manager') or is_owner):
            raise AccessError(self.env._('You do not have access to this tenant database.'))
        if tenant.type != 'build' or tenant.state != 'done':
            raise AccessError(self.env._('The tenant database is not ready.'))
        _, admin_id = tenant.sudo().xmlid_lookup('base.user_admin')
        return {
            'user_id': self.env.uid,
            'build': str(tenant.id),
            'build_user_id': admin_id,
            'build_login': False,
        }

    @api.private
    def user_has_access(self):
        return bool(self._get_authorized_build())

    @api.private
    def get_build_url(self):
        build = self._get_authorized_build()
        return build.get_url() if build else None

    @api.model_create_multi
    def create(self, vals_list):
        res = super(Token, self).create(vals_list)
        self.env['saas.log'].log_db_authed(res)
        return res
