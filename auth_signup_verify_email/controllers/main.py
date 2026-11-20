# Copyright 2015 Antiun Ingeniería, S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import logging
import secrets

from email_validator import EmailNotValidError, validate_email
from werkzeug.exceptions import NotFound

from odoo.exceptions import UserError
from odoo.http import request, route

from odoo.addons.auth_signup.controllers.main import AuthSignupHome
from odoo.addons.auth_signup.models.res_users import SignupError

_logger = logging.getLogger(__name__)


class SignupVerifyEmail(AuthSignupHome):
    @route()
    def web_auth_signup(self, *args, **kwargs):
        if (
            request.httprequest.method == "POST"
            and not request.params.get("token")
            and not request.session.get("auth_signup_token")
        ):
            return self.passwordless_signup()
        return super().web_auth_signup(*args, **kwargs)

    def _prepare_passwordless_signup_values(self, qcontext):
        login = validate_email(qcontext.get("login") or "").normalized
        name = (qcontext.get("name") or "").strip()
        if not name:
            raise UserError(request.env._("Please enter your name."))
        return {"login": login, "email": login, "name": name, "password": secrets.token_urlsafe(32)}

    def passwordless_signup(self):
        qcontext = self.get_auth_signup_qcontext()
        if not qcontext.get("signup_enabled"):
            raise NotFound()

        try:
            values = self._prepare_passwordless_signup_values(qcontext)
        except EmailNotValidError:
            qcontext["error"] = request.env._("Please enter a valid email address.")
            return request.render("auth_signup.signup", qcontext)
        except UserError as error:
            qcontext["error"] = error.args[0]
            return request.render("auth_signup.signup", qcontext)

        users = request.env["res.users"].sudo().with_context(create_user=True)
        try:
            with request.env.cr.savepoint():
                login, _password = users.signup(values)
                users.reset_password(login)
        except (SignupError, UserError):
            _logger.warning("Passwordless signup did not complete.")
            qcontext["error"] = request.env._("Could not send a signup email. Please try again later.")
            return request.render("auth_signup.signup", qcontext)

        qcontext["message"] = request.env._("Check your email to activate your account!")
        return request.render("auth_signup.reset_password", qcontext)
