from odoo import api, models
from odoo.exceptions import AccessError


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.su:
            return super().create(vals_list)
        allowed_groups = self.env.user.all_group_ids
        with self.env.cr.savepoint():
            users = super().create(vals_list)
            for user, vals in zip(users.sudo(), vals_list):
                if 'group_ids' in vals and user.all_group_ids - allowed_groups:
                    raise AccessError(self.env._('You can only assign groups you already have.'))
        return users

    def write(self, vals):
        if self.env.su or 'group_ids' not in vals:
            return super().write(vals)
        allowed_groups = self.env.user.all_group_ids
        original_groups = {user.id: user.all_group_ids for user in self.sudo()}
        with self.env.cr.savepoint():
            result = super().write(vals)
            for user in self.sudo():
                if user.all_group_ids - original_groups[user.id] - allowed_groups:
                    raise AccessError(self.env._('You can only assign groups you already have.'))
        return result


class ResGroups(models.Model):
    _inherit = 'res.groups'

    def write(self, vals):
        if self.env.su or 'implied_ids' not in vals:
            return super().write(vals)
        allowed_groups = self.env.user.all_group_ids | self.env.ref('base.group_no_one')
        original_groups = {group.id: group.all_implied_ids for group in self.sudo()}
        with self.env.cr.savepoint():
            result = super().write(vals)
            for group in self.sudo():
                if group.all_implied_ids - original_groups[group.id] - allowed_groups:
                    raise AccessError(self.env._('You can only imply groups you already have.'))
        return result
