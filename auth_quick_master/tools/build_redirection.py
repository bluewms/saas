# Copyright 2019 Denis Mudarisov <https://it-projects.info/team/trojikman>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import jinja2
import os


def build_redirection(build_url):
    path = os.path.realpath(os.path.join(os.path.dirname(__file__), '..', 'views'))
    loader = jinja2.FileSystemLoader(path)
    env = jinja2.Environment(loader=loader, autoescape=True)

    return env.get_template('auth_quick_master_redirect.html').render({'build_url': build_url})


def build_confirmation(action_url, params, csrf_token, message):
    path = os.path.realpath(os.path.join(os.path.dirname(__file__), '..', 'views'))
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(path), autoescape=True)
    return env.get_template('auth_quick_master_confirm.html').render({
        'action_url': action_url,
        'params': {key: value for key, value in params.items() if value is not None},
        'csrf_token': csrf_token,
        'message': message,
    })
