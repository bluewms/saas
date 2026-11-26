from collections import defaultdict
from urllib.parse import urlsplit

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SaasDb(models.Model):
    _inherit = "saas.db"

    domain_name_id = fields.Many2one(
        "saas.domain.name", copy=False, domain="[('operator_id', '=', operator_id)]"
    )

    _domain_name_id_unique = models.Constraint(
        "unique(domain_name_id)",
        "Cannot assign same domain to multiple builds",
    )

    def get_url(self):
        url = super().get_url()
        domain = self.sudo().domain_name_id.name
        if not domain:
            return url
        parsed = urlsplit(url)
        host = f'{domain}:{parsed.port}' if parsed.port is not None else domain
        return parsed._replace(netloc=host).geturl()

    @api.constrains('domain_name_id', 'operator_id')
    def _check_domain_operator(self):
        for record in self:
            if record.domain_name_id and record.domain_name_id.operator_id != record.operator_id:
                raise ValidationError(self.env._('The domain name belongs to another operator.'))

    @api.model_create_multi
    def create(self, vals_list):
        records = super(SaasDb, self).create(vals_list)
        DomainName = self.env["saas.domain.name"]
        for record in records:
            if record.domain_name_id and record.state == 'done':
                DomainName.with_delay()._run_domain_operations(
                    record.operator_id.id, [["map", record.domain_name_id.name, record.name]]
                )

        return records

    def _finalize_build(self):
        self.ensure_one()
        if self.type == 'build' and self.state == 'creating' and self.domain_name_id:
            self.operator_id.map_domain(self.domain_name_id.name, self.name)
        return super()._finalize_build()

    def write(self, vals):
        domain_name_ids_before = {}
        batch_domain_operations = defaultdict(list)

        for record in self:
            domain_name_ids_before[record.id] = record.domain_name_id

        res = super(SaasDb, self).write(vals)

        for record in self:
            if record.domain_name_id == domain_name_ids_before[record.id]:
                continue

            if domain_name_ids_before[record.id]:
                batch_domain_operations[record].append(
                    ["unmap", domain_name_ids_before[record.id].name],
                )

            if record.domain_name_id:
                batch_domain_operations[record].append(
                    ["map", record.domain_name_id.name, record.name],
                )

        DomainName = self.env["saas.domain.name"]
        for build, operations in batch_domain_operations.items():
            DomainName.with_delay()._run_domain_operations(
                build.operator_id.id, operations
            )
        return res
