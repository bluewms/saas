# Copyright 2018 Ivan Yelizariev <https://it-projects.info/team/yelizariev>
# Copyright 2019 Denis Mudarisov <https://it-projects.info/team/trojikman>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import secrets
from dateutil.relativedelta import relativedelta
import logging
import urllib.parse
from ..tools.build_redirection import build_redirection

from odoo import api, fields, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)


class Token(models.Model):
    _name = 'auth_quick_master.token'
    _description = 'Authentication Token'

    user_id = fields.Many2one('res.users', 'Master User', default=lambda s: s.env.user.id, required=True, ondelete='cascade')
    build = fields.Char('Build Reference')
    build_login = fields.Char('User Login')
    build_user_id = fields.Integer('User ID')
    token = fields.Char(default=lambda self: secrets.token_urlsafe(32), readonly=True, copy=False, index=True, groups='base.group_system')

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise AccessError(self.env._('Authentication tokens must be issued through the login flow.'))
        vals_list = [dict(vals, token=secrets.token_urlsafe(32)) for vals in vals_list]
        return super().create(vals_list)

    @api.private
    def is_obsolete(self):
        self.ensure_one()
        is_obsolete = self.create_date + relativedelta(minutes=5) < fields.Datetime.now()
        if is_obsolete:
            _logger.info('Authentication token %s has expired', self.id)
        return is_obsolete

    @api.private
    def user_has_access(self):
        """Can be extended"""
        self.ensure_one()
        has_access = self.user_id.active and self.user_id.has_group('auth_quick_master.group_auth_quick')
        if not has_access:
            _logger.info('User doesn\'t have access: %s', self.user_id.login)
        return has_access

    @api.private
    def get_build_url(self):
        """To be extended"""
        self.ensure_one()
        return None

    def _prepare_token_values(self, build, build_user_id=None, build_login=None):
        if not self.env.user.active or not self.env.user.has_group('auth_quick_master.group_auth_quick'):
            raise AccessError(self.env._("You don't have access to quick authentication."))
        return {
            'user_id': self.env.uid,
            'build': str(build),
            'build_user_id': int(build_user_id or 0),
            'build_login': build_login or False,
        }

    def _check_build_reference(self, build):
        self.ensure_one()
        return build is None or str(build) == self.build

    @api.private
    def redirect_with_token(self, build_url, build_id, build_login):
        vals = self._prepare_token_values(build_id, build_login=build_login)
        # Issuing and consuming tokens are the only privileged token writes.
        token_obj = self.sudo().create(vals)
        build_url = token_obj.get_build_url() or build_url
        url = urllib.parse.urljoin(build_url, '/auth_quick/check-token?token={}'.format(token_obj.token))

        return build_redirection(url)

    @api.autovacuum
    def _gc_expired_tokens(self):
        cutoff = fields.Datetime.now() - relativedelta(minutes=5)
        self.sudo().search([('create_date', '<', cutoff)], limit=1000).unlink()
