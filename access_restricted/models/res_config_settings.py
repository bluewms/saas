from odoo import api, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    def _may_configure_implied_groups(self):
        return self.env.su or self.env.user.has_group(
            'access_restricted.group_allow_add_implied_from_settings'
        )

    @api.model
    def _get_classified_fields(self, fnames=None):
        classified = super()._get_classified_fields(fnames)
        if not self._may_configure_implied_groups():
            allowed_groups = self.env.user.all_group_ids
            classified['group'] = [
                entry for entry in classified['group'] if entry[2] <= allowed_groups
            ]
        return classified

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        result = super().fields_get(allfields, attributes)
        if self._may_configure_implied_groups() or (attributes is not None and 'readonly' not in attributes):
            return result

        allowed_groups = self.env.user.all_group_ids
        for name, info in result.items():
            if name.startswith('group_') and not self.env.ref(self._fields[name].implied_group) <= allowed_groups:
                info['readonly'] = True
        return result
