from . import models


def post_init_hook(env):
    limit = env.ref('access_limit_max_users.max_users_limit')
    limit.max_records = env['res.users'].search_count(limit._record_domain())
