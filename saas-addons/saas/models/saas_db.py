# Copyright 2018 Ivan Yelizariev <https://it-projects.info/team/yelizariev>
# Copyright 2019 Denis Mudarisov <https://it-projects.info/team/trojikman>
# Copyright 2020 Eugene Molotov <https://it-projects.info/team/em230418>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

from odoo.addons.saas_cluster_simple.main import validate_database_name
from ..tools import check_management_database


class SAASDB(models.Model):
    _name = 'saas.db'
    _inherit = 'mail.thread'
    _description = 'Build'

    name = fields.Char('Name', help='Technical Database name', readonly=True, required=True, copy=False, index=True)
    operator_id = fields.Many2one('saas.operator', required=True, ondelete='restrict')
    type = fields.Selection([
        ('template', 'Template DB'),
        ('build', 'Normal Build'),
    ], string='DB Type', default='build')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('creating', 'Provisioning'),
        ('done', 'Ready'),
    ], default='draft')

    _name_operator_unique = models.Constraint(
        'unique(name, operator_id)',
        'A database name must be unique per operator.',
    )

    @api.constrains('name', 'operator_id')
    def _check_database_name(self):
        for record in self:
            validate_database_name(record.name)
            if record.operator_id.type == 'local' and record.name == self.env.cr.dbname:
                raise ValidationError(self.env._('The SaaS management database cannot be used as a tenant.'))

    def _check_management_access(self, operation='write'):
        check_management_database(self.env)
        self.check_access(operation)
        if not self.env.su and not self.env.user.has_group('saas.group_manager'):
            raise AccessError(self.env._('Only SaaS managers can manage tenant databases.'))

    def unlink(self):
        # Check before touching the separate tenant database, whose transaction
        # cannot be rolled back with this management transaction.
        self._check_management_access('unlink')
        self.drop_db()
        return super(SAASDB, self).unlink()

    @api.private
    def create_db(self, template_db, demo, lang='en_US', callback_obj=None, callback_method=None):
        self.ensure_one()
        db_name = self.name
        self.state = 'creating'
        self.operator_id._create_db(template_db, db_name, demo, lang)
        if self.type == 'template':
            self.state = 'done'
        self.env['saas.log'].log_db_created(self)
        if callback_obj and callback_method:
            getattr(callback_obj, callback_method)()

    def _finalize_build(self):
        self.ensure_one()
        if self.state == 'done':
            return True
        if self.type != 'build' or self.state != 'creating':
            raise ValidationError(self.env._('Only a provisioned tenant database can be marked ready.'))
        # write() synchronizes tenant settings. A failed synchronization rolls
        # back this ready state, so login stays closed until the job succeeds.
        self.state = 'done'
        return True

    @api.private
    def drop_db(self):
        for r in self:
            r.operator_id._drop_db(r.name)
            r.state = 'draft'
            self.env['saas.log'].log_db_dropped(r)

    def get_url(self):
        # TODO: need possibility to use custom domain
        self.ensure_one()
        self.check_access('read')
        return self.sudo().operator_id.get_db_url(self)

    def action_get_build_access(self):
        self.ensure_one()
        self.check_access('read')
        auth_url = '/saas/auth-to-build/' + str(self.id)
        return {
            'type': 'ir.actions.act_url',
            'target': 'new',
            'url': auth_url,
        }

    def write(self, vals):
        res = super(SAASDB, self).write(vals)
        if not self.env.context.get("writing_from_refresh_data"):  # Do not run "refresh_data", if already running it
            self.refresh_data()
        return res

    def action_refresh_data(self):
        self._check_management_access()
        return self.refresh_data()

    @api.private
    def refresh_data(self, should_read_from_build=True, should_write_to_build=True):
        self.flush_model()
        for record in self.filtered(lambda record: (record.type, record.state) == ("build", "done")).with_context(writing_from_refresh_data=True):
            if should_read_from_build:
                vals = record.read_values_from_build()
                if vals:
                    record.write(vals)

            if should_write_to_build:
                record.write_values_to_build()
                record.operator_id._signal_changes(record.name)

    @api.private
    def write_values_to_build(self):
        pass

    @api.private
    def read_values_from_build(self):
        return {}

    @api.private
    def execute_kw(self, model, method, *args, **kwargs):
        self.ensure_one()
        return self.operator_id.build_execute_kw(self, model, method, args, kwargs)

    @api.private
    def xmlid_lookup(self, xmlid):
        return self.execute_kw("ir.model.data", "_xmlid_lookup", xmlid)

    @api.private
    def xmlid_to_res_model_res_id(self, xmlid, raise_if_not_found=False):
        return self.execute_kw("ir.model.data", "_xmlid_to_res_model_res_id", xmlid, raise_if_not_found=raise_if_not_found)

    def action_install_missing_mandatory_modules(self):
        self._check_management_access()
        for build in self.filtered(lambda x: x.state in ('creating', 'done')):
            operator = build.operator_id
            operator._install_modules(build.name, [('name', 'in', operator.get_mandatory_modules())])
