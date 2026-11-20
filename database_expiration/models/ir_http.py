# Copyright 2020 Eugene Molotov <https://it-projects.info/team/em230418>
# Copyright 2021 Denis Mudarisov <https://github.com/trojikman>
# License MIT (https://opensource.org/licenses/MIT).

from urllib.parse import urlsplit

from odoo import fields, models


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        info = super().session_info()
        config = self.env['ir.config_parameter'].sudo()
        try:
            expiration = fields.Datetime.to_datetime(config.get_str('database_expiration_date', ''))
        except ValueError:
            return info
        if not expiration:
            return info

        delta = expiration - fields.Datetime.now()
        warning_days = max(config.get_int('database_expiration_warning_delay', 7), 1)
        if delta.days > warning_days:
            return info
        if delta.days < 0:
            message = self.env._('Your database is expired')
        elif delta.days == 0:
            message = self.env._('Your database will expire today')
        elif delta.days == 1:
            message = self.env._('Your database will expire tomorrow')
        else:
            message = self.env._('Your database will expire in %s days', delta.days)

        url = config.get_str('database_expiration_details_link', '')
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                url = None
        except ValueError:
            url = None
        self._set_database_block_notice(
            info, message, warning=delta.days >= 0, url=url,
            label=config.get_str('database_expiration_details_link_label', '') or self.env._('Details'),
        )
        return info
