from odoo import fields, models
from odoo.exceptions import UserError


FAILED = "failed"
ARCHIVED = "archived"


class SaasDb(models.Model):
    _inherit = "saas.db"

    active = fields.Boolean("Active", default=True)
    origin_build_id = fields.Many2one(
        "saas.db", related="origin_backup_id.origin_build_id", readonly=True
    )
    origin_backup_id = fields.Many2one(
        "saas.db.backup", string="Origin backup", readonly=True
    )
    backup_ids = fields.One2many("saas.db.backup", "origin_build_id", readonly=True)
    backup_count = fields.Integer("Backup count", compute="_compute_backups")
    state = fields.Selection(
        selection_add=[(FAILED, "Failed"), (ARCHIVED, "Archived")],
        ondelete={FAILED: "set default", ARCHIVED: "set default"},
    )

    def _compute_backups(self):
        for record in self:
            record.backup_count = len(record.backup_ids.ids)

    def action_create_backup(self):
        self.ensure_one()
        self._check_management_access()
        if self.state != 'done':
            raise UserError(self.env._('Only a ready database can be backed up.'))
        backup = self.env["saas.db.backup"].create({"origin_build_id": self.id})
        return backup._create_backup()

    def action_view_backups(self):
        self.ensure_one()
        self.check_access('read')
        return {
            "type": "ir.actions.act_window",
            "name": "Backups of %s" % (self.name,),
            "res_model": "saas.db.backup",
            "views": [[False, "list"], [False, "form"]],
            "domain": [["origin_build_id", "=", self.id]],
        }

    def unlink(self):
        if self.filtered('backup_ids'):
            raise UserError(self.env._('Remove or reassign the backup records before deleting their source database.'))
        return super().unlink()
