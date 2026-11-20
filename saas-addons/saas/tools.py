import os

from odoo.exceptions import AccessError


def check_management_database(env):
    # A per-database parameter is writable by a tenant administrator. Bind
    # privileged SaaS operations to server configuration instead.
    master_database = os.environ.get('SAAS_MASTER_DATABASE', '').strip()
    if not master_database or env.cr.dbname != master_database:
        raise AccessError(env._('SaaS operations require the configured management database. Set SAAS_MASTER_DATABASE on the server.'))
