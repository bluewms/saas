import json

from odoo import api, fields, models
from odoo.tools import SQL


class QueueJob(models.Model):
    _inherit = "queue.job"

    # OCA 20 stores the recordset in records rather than a record_ids column.
    # Keep the existing SaaS domains working without adding a stored column.
    record_ids = fields.Json(compute='_compute_record_ids', search='_search_record_ids')

    @api.depends('records')
    def _compute_record_ids(self):
        for job in self:
            job.record_ids = job.records.ids

    def _search_record_ids(self, operator, value):
        # Domain normalization converts the legacy like operand to text.
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                return fields.Domain.FALSE
        if operator not in ('like', '=', 'in') or not isinstance(value, (list, tuple)):
            return NotImplemented
        if not value or any(not isinstance(record_id, int) or isinstance(record_id, bool) for record_id in value):
            return fields.Domain.FALSE
        # Start with an ORM query so job access rules remain enforced. OCA's
        # JSON field may store either an object or a JSON-encoded string.
        query = self._search([])
        records = SQL.identifier(self._table, 'records')
        query.add_where(SQL(
            "((CASE WHEN jsonb_typeof(%s) = 'string' THEN (%s #>> '{}')::jsonb ELSE %s END) -> 'ids') @> %s::jsonb",
            records, records, records, json.dumps(list(value)),
        ))
        return fields.Domain('id', 'in', query)

    def write(self, vals):
        res = super(QueueJob, self).write(vals)
        self.flush_model()
        return res
