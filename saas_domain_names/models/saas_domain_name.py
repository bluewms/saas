from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.addons.host2db.override import normalize_domain
import logging

_logger = logging.getLogger(__name__)


class DomainName(models.Model):
    _name = "saas.domain.name"
    _description = "Web domain"

    name = fields.Char("Domain", required=True)
    operator_id = fields.Many2one("saas.operator", string="Operator", required=True)

    _name_unique = models.Constraint("unique(name)", "Domain names must be unique")

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._normalize_domain_values(vals) for vals in vals_list]
        return super().create(vals_list)

    def write(self, vals):
        self.check_access('write')
        before = [(record.operator_id.id, record.name) for record in self]
        res = super().write(self._normalize_domain_values(vals))
        if {'name', 'operator_id'} & vals.keys():
            for record, (old_operator_id, old_name) in zip(self, before):
                if old_operator_id == record.operator_id.id and old_name == record.name:
                    continue
                self.with_delay()._run_domain_operations(old_operator_id, [['unmap', old_name]])
                self.with_delay()._run_domain_operations(record.operator_id.id, [['map', record.name]])
        return res

    @api.constrains('operator_id')
    def _check_assigned_build_operator(self):
        for record in self:
            if self.env['saas.db'].with_context(active_test=False).search_count([
                ('domain_name_id', '=', record.id), ('operator_id', '!=', record.operator_id.id),
            ]):
                raise ValidationError(self.env._('An assigned domain must stay on its build operator.'))

    def _normalize_domain_values(self, vals):
        vals = dict(vals)
        if 'name' in vals:
            try:
                vals['name'] = normalize_domain(vals['name'])
            except ValueError:
                raise ValidationError(self.env._('Enter a valid domain name without a scheme, port, or path.'))
        return vals

    @api.model
    def _run_domain_operations(self, operator_id, operations):
        operator = self.env["saas.operator"].sudo().browse(operator_id)
        domains = set()
        for op in operations:
            if len(op) < 2 or op[0] not in ('map', 'unmap'):
                raise ValidationError(self.env._('Invalid domain operation.'))
            domains.add(normalize_domain(op[1]))
        # Jobs can run out of order during a restored-build handover. Reconcile
        # each hostname with its current owner instead of replaying stale writes.
        for name in sorted(domains):
            domain = self.search([('name', '=', name), ('operator_id', '=', operator.id)], limit=1)
            build = self.env['saas.db'].with_context(active_test=False).search([
                ('domain_name_id', '=', domain.id), ('operator_id', '=', operator.id),
            ], limit=1) if domain else self.env['saas.db']
            if build:
                operator.map_domain(name, build.name)
            else:
                operator.unmap_domain(name)

    def unlink(self):
        self.check_access('unlink')
        for record in self:
            record.operator_id.unmap_domain(record.name)
        return super(DomainName, self).unlink()
