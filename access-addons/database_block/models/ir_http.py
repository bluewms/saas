# Copyright 2020 Eugene Molotov <https://it-projects.info/team/em230418>
# License MIT (https://opensource.org/licenses/MIT).

from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def _set_database_block_notice(self, session_info, message, *, warning=False, url=None, label=None):
        previous = session_info.get('database_block_notice')
        if not previous or (previous['warning'] and not warning):
            session_info['database_block_notice'] = {
                'message': message, 'warning': warning, 'url': url, 'label': label,
            }
