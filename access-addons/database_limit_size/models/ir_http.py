# Copyright 2020 Eugene Molotov <https://it-projects.info/team/em230418>
# License MIT (https://opensource.org/licenses/MIT).

import os

from odoo import models
from odoo.tools import SQL, human_size


def get_directory_size(start_path):
    total_size = 0
    for directory, _subdirectories, filenames in os.walk(start_path):
        for filename in filenames:
            try:
                path = os.path.join(directory, filename)
                if not os.path.islink(path):
                    total_size += os.path.getsize(path)
            except FileNotFoundError:
                # A concurrent attachment deletion can remove the file after os.walk.
                continue
    return total_size


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        info = super().session_info()
        limit = self.env['ir.config_parameter'].sudo().get_int('database_limit_size', 0)
        if limit <= 0:
            return info

        [(database_size,)] = self.env.execute_query(SQL('SELECT pg_database_size(%s)', self.env.cr.dbname))
        filestore = self.env['ir.attachment']._filestore()
        size = database_size + get_directory_size(filestore)
        if size > limit:
            message = self.env._('Database size limit exceeded (%(size)s / %(limit)s)',
                                 size=human_size(size), limit=human_size(limit))
            self._set_database_block_notice(info, message)
        elif size * 10 > limit * 9:
            message = self.env._('Database size is approaching the limit (%(size)s / %(limit)s)',
                                 size=human_size(size), limit=human_size(limit))
            self._set_database_block_notice(info, message, warning=True)
        return info
