# Copyright 2018 Ivan Yelizariev <https://it-projects.info/team/yelizariev>
# Copyright 2019 Denis Mudarisov <https://it-projects.info/team/trojikman>
# Copyright 2020-2021 Eugene Molotov <https://it-projects.info/team/em230418>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from collections import defaultdict
import string
from urllib.parse import urlsplit

import psycopg2
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
import odoo.addons.saas_cluster_simple.main as cluster
from odoo.addons.queue_job.exception import RetryableJobError
from ..tools import check_management_database


class SAASOperator(models.Model):
    _name = 'saas.operator'
    _description = 'Database Operator'

    name = fields.Char(required=True)
    # list of types can be extended via selection_add
    type = fields.Selection([
        ('local', 'Same Instance'),
    ], 'Type', default='local', required=True)
    global_url = fields.Char('Master URL (Server-to-Server)', required=True, help='URL for server-to-server communication ')
    # host = fields.Char()
    # port = fields.Char()
    db_url_template = fields.Char('DB URLs', help='Avaialble variables: {db_name}')
    template_operator_ids = fields.One2many('saas.template.operator', 'operator_id')

    build_count = fields.Integer(compute="_compute_build_count")

    @api.constrains('global_url', 'db_url_template')
    def _check_urls(self):
        for operator in self:
            urls = [operator.global_url]
            if operator.db_url_template:
                try:
                    urls.append(operator.db_url_template.format(db_name='tenant'))
                except (KeyError, ValueError, AttributeError):
                    raise ValidationError(self.env._('Use {db_name} as the database URL placeholder.'))
            for url in urls:
                try:
                    parsed = urlsplit(url or '')
                    parsed.port
                except ValueError:
                    raise ValidationError(self.env._('Configure a valid HTTP or HTTPS operator URL.'))
                if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                    raise ValidationError(self.env._('Configure a valid HTTP or HTTPS operator URL without credentials.'))

    def _compute_build_count(self):
        counts = dict(self.env['saas.db']._read_group(
            [('operator_id', 'in', self.ids)], ['operator_id'], ['__count'],
        ))
        for record in self:
            record.build_count = counts.get(record, 0)

    def _check_management_access(self, operation='write'):
        self._check_management_database()
        self.check_access(operation)
        if not self.env.su and not self.env.user.has_group('saas.group_manager'):
            raise AccessError(self.env._('Only SaaS managers can manage database operators.'))

    def _check_management_database(self):
        check_management_database(self.env)

    def _check_local_database(self, db_name):
        self._check_management_database()
        cluster.validate_database_name(db_name)
        if db_name == self.env.cr.dbname:
            raise AccessError(self.env._('The SaaS management database cannot be operated on as a tenant.'))

    def action_show_builds(self):
        self.ensure_one()
        action = {
            "type": "ir.actions.act_window",
            "name": "Builds and templates",
            "res_model": "saas.db",
            "view_mode": "list,form",
            "domain": [["operator_id", "=", self.id]],
            "views": [[False, "list"], [False, "form"]],
        }
        return action

    @api.private
    def get_mandatory_modules(self):
        return ["auth_quick"]

    def _create_db(self, template_db, db_name, demo, lang='en_US'):
        """Synchronous db creation"""
        if not self:
            return
        elif self.type != 'local':
            raise NotImplementedError()

        self._check_local_database(db_name)
        return cluster.create_db(template_db, db_name, demo, lang)

    def _drop_db(self, db_name):
        if not self:
            return
        elif self.type != 'local':
            raise NotImplementedError()

        self._check_local_database(db_name)
        return cluster.drop_db(db_name)

    def _install_modules(self, db_name, modules):
        if self.type != 'local':
            raise NotImplementedError()

        self._check_local_database(db_name)
        return cluster.install_modules(db_name, modules)

    @api.private
    def install_modules(self, template_id, template_operator_id):
        self._check_management_database()
        self.ensure_one()
        modules = [module.name for module in template_id.template_module_ids]
        modules = [('name', 'in', self.get_mandatory_modules() + modules)]
        self._install_modules(template_operator_id.operator_db_name, modules)
        template_operator_id.state = 'post_init'
        self.with_delay().post_init(template_id, template_operator_id)

    def _post_init(self, db_name, template_post_init):
        if self.type != 'local':
            raise NotImplementedError()

        self._check_local_database(db_name)
        return cluster.post_init(db_name, template_post_init)

    @api.private
    def post_init(self, template_id, template_operator_id):
        self._check_management_database()
        self.ensure_one()
        self._post_init(template_operator_id.operator_db_name, template_id.template_post_init)
        template_operator_id.state = 'done'

    def _map_domain(self, domain, db_name):
        self._check_management_database()
        if self.type != "local":
            raise NotImplementedError()

        return cluster.map_domain(domain, db_name)

    @api.private
    def map_domain(self, domain, db_name):
        self._check_management_database()
        self.ensure_one()
        # TODO: add check if domain is valid
        self._map_domain(domain, db_name)

    def _unmap_domain(self, domain):
        self._check_management_database()
        if self.type != "local":
            raise NotImplementedError()

        return cluster.unmap_domain(domain)

    @api.private
    def unmap_domain(self, domain):
        self._check_management_database()
        self.ensure_one()
        if not domain:
            return
        self._unmap_domain(domain)

    def _signal_changes(self, db_name):
        self._check_local_database(db_name)
        cluster.signal_changes(db_name)

    @api.private
    def get_db_url(self, db):
        # TODO: use mako for url templating
        self.ensure_one()
        if not self.db_url_template:
            raise UserError(self.env._('Configure the database URL template on the operator first.'))
        return self.db_url_template.format(db_name=db.name)

    @api.private
    def generate_db_name(self):
        self.ensure_one()
        sequence = self.env['ir.sequence'].next_by_code('saas.db')
        return "fast-build-{unique_id}".format(unique_id=sequence)

    def _get_mandatory_args(self, db):
        self.ensure_one()
        return {
            'master_url': self.global_url,
            'build_id': str(db.id)
        }

    @staticmethod
    def _get_mandatory_code():
        master = "env['ir.config_parameter'].set_str('auth_quick.master', {master_url!r})\n"
        build = "env['ir.config_parameter'].set_str('auth_quick.build', {build_id!r})\n"
        return master + build

    def _build_execute_kw(self, db_name, model, method, args, kwargs):
        if self.type != 'local':
            raise NotImplementedError()

        self._check_local_database(db_name)
        return cluster.execute_kw(db_name, model, method, args, kwargs)

    @api.private
    def build_execute_kw(self, build, model, method, args=None, kwargs=None):
        self._check_management_database()
        self.ensure_one()
        build.ensure_one()
        if build.operator_id != self:
            raise UserError(self.env._('The build belongs to another operator.'))
        args = args or []
        kwargs = kwargs or {}
        return self._build_execute_kw(build.name, model, method, args, kwargs)

    @api.private
    def build_post_init(self, build, post_init_action=None, key_value_dict=None):
        self._check_management_database()
        if post_init_action is None:
            post_init_action = ""

        key_value_dict = dict(key_value_dict or {})

        key_value_dict.update(self._get_mandatory_args(build))
        code = self._get_mandatory_code() + post_init_action
        action = {
            'name': 'Build Code Eval',
            'state': 'code',
            'model_id': 1,
            'code': string.Formatter().vformat(code, (), SafeDict(**key_value_dict))
        }
        try:
            action_ids = self.build_execute_kw(build, 'ir.actions.server', 'create', [action])
            self.build_execute_kw(build, 'ir.actions.server', 'run', [action_ids])
            self.build_execute_kw(build, 'ir.actions.server', 'unlink', [action_ids])
        except psycopg2.OperationalError as e:
            # TODO: this is very stupid hack that can be handled only in local instance operators
            raise RetryableJobError(str(e))

    def _create_backup_internal(self, db_name):
        if self.type != "local":
            raise NotImplementedError()

        self._check_local_database(db_name)
        return cluster.create_backup(db_name)

    def _create_backup(self, db_name):
        self._check_management_database()
        self.ensure_one()
        return self._create_backup_internal(db_name)

    def _deploy_backup_internal(self, backup_name):
        self._check_management_database()
        if self.type != "local":
            raise NotImplementedError()

        return cluster.deploy_backup(backup_name)

    def _deploy_backup(self, backup_name):
        self._check_management_database()
        self.ensure_one()
        return self._deploy_backup_internal(backup_name)

    def write(self, vals):
        self._check_management_access()
        res = super(SAASOperator, self).write(vals)
        if 'global_url' in vals:
            for record in self:
                record._update_global_url(vals['global_url'])
        return res

    def _update_global_url(self, url):
        self.ensure_one()
        builds = self.env['saas.db'].search([
            ('operator_id', '=', self.id), ('type', '=', 'build'), ('state', '=', 'done'),
        ])
        for build in builds:
            self.build_execute_kw(build, 'ir.config_parameter', 'set_str', ['auth_quick.master', url])

    @api.private
    def notify_users(self, message, title=None, message_type=None):
        manager_users = self.env.ref("saas.group_manager").user_ids
        manager_users._bus_send('simple_notification', {
            'message': message, 'title': title, 'sticky': True,
            'type': 'success' if message_type == 'success' else 'info',
        })


class SafeDict(defaultdict):
    def __missing__(self, key):
        return '{' + key + '}'
