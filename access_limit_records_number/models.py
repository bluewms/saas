# Copyright 2018 Ivan Yelizariev <https://it-projects.info/team/yelizariev>
# License MIT (https://opensource.org/licenses/MIT).

from ast import literal_eval

from odoo import Command, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import SQL


class BaseLimitRecordsNumber(models.Model):
    _name = 'base.limit.records_number'
    _description = 'Restrictions for number of records'
    _inherits = {'base.automation': 'action_rule_id'}

    action_rule_id = fields.Many2one('base.automation', required=True, ondelete='cascade')
    max_records = fields.Integer(string='Maximum Records')
    domain = fields.Char(default='[]', required=True)

    _nonnegative_limit = models.Constraint('CHECK (max_records >= 0)', 'The record limit cannot be negative.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('action_rule_id'):
                continue
            vals.update({
                'trigger': 'on_create_or_write',
                'action_server_ids': [Command.create({
                    'name': self.env._('Check record limit'),
                    'model_id': vals.get('model_id'),
                    'state': 'code',
                    'code': "env['base.limit.records_number'].verify_table()",
                })],
            })
        return super().create(vals_list)

    def _record_domain(self):
        self.ensure_one()
        try:
            return fields.Domain(literal_eval(self.domain))
        except (SyntaxError, TypeError, ValueError) as error:
            raise ValidationError(self.env._('Enter a valid record limit domain.')) from error

    @api.constrains('domain', 'model_id')
    def _check_domain(self):
        for rule in self:
            self.env[rule.model_id.model].search_count(rule._record_domain(), limit=1)

    @api.model
    @api.private
    def verify_table(self):
        model_name = self.env.context.get('active_model')
        if not model_name or not self.env.su:
            raise AccessError(self.env._('Record limits are checked by the automation engine.'))
        rules = self.search([('model_id.model', '=', model_name), ('active', '=', True)], order='id')
        for rule in rules:
            # Serialize checks with one updated row per rule so a concurrent
            # transaction with a stale snapshot retries before counting.
            self.env.cr.execute(SQL(
                'UPDATE base_limit_records_number SET write_date = write_date WHERE id = %s', rule.id,
            ))
            count = self.env[model_name].with_context(active_test=True).search_count(rule._record_domain())
            if count > rule.max_records:
                raise ValidationError(self.env._(
                    '%(model)s allows at most %(limit)s records. This change would bring the total to %(count)s.',
                    model=rule.model_id.name, limit=rule.max_records, count=count,
                ))

    @api.model
    @api.private
    def set_max_records(self, xmlid, max_records):
        rule = self.env.ref(xmlid)
        if rule._name != self._name:
            raise ValidationError(self.env._('The identifier must refer to a record limit.'))
        rule.max_records = max_records
