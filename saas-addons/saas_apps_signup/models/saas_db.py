# Copyright 2020 Eugene Molotov <https://it-projects.info/team/em230418>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

import logging
from urllib.parse import urlsplit

from psycopg2.errors import UniqueViolation

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.host2db.override import normalize_domain
from odoo.addons.saas_cluster_simple.main import validate_database_name

_logger = logging.getLogger(__name__)


class SaasDb(models.Model):

    _inherit = 'saas.db'

    database_limit_size = fields.Float(default=lambda self: self.env["ir.config_parameter"].sudo().get_float("saas_apps_signup.database_limit_size_default", 0.0))
    is_admin_user_language_installed = fields.Boolean("Is admin user's language installed?")

    def _get_domain_of_queue_job_records(self):
        return [
            "|", "&",
            ("model_name", "=", "contract.contract"),
            ("record_ids", "like", [self.contract_id.id]),
        ] + super(SaasDb, self)._get_domain_of_queue_job_records()

    @api.model_create_multi
    def create(self, vals_list):

        if not self.env.su and not self.env.user.has_group("saas.group_manager"):
            if self.env['saas.db'].search_count([
                ("state", "=", "draft"),
                ("admin_user", "=", self.env.user.id),
            ], limit=1):
                raise ValidationError(self.env._('You cannot create more than one draft database.'))

        return super(SaasDb, self).create(vals_list)

    @api.model
    def _get_website_build_slot(self, operator, name):
        operator.ensure_one()
        try:
            slug = normalize_domain(name)
            if '.' in slug:
                raise ValueError()
            validate_database_name(slug)
        except (ValueError, UserError):
            raise ValidationError(self.env._('Enter a subdomain using letters, numbers, and hyphens.')) from None

        if not operator.db_url_template:
            raise ValidationError(self.env._('This offer has no customer domain configured.'))
        url = operator.db_url_template.format(db_name=slug)
        host = urlsplit(url).hostname
        if not host or not host.startswith(f'{slug}.'):
            raise ValidationError(self.env._('This offer has no customer domain configured.'))
        if (self.with_context(active_test=False).search_count([
            ('name', '=', slug), ('operator_id', '=', operator.id),
        ], limit=1) or self.env['saas.domain.name'].search_count([('name', '=', host)], limit=1)):
            raise ValidationError(self.env._('This subdomain is already in use.'))
        return {'database_name': slug, 'domain': url, 'host': host}

    @api.model
    def _create_website_build_draft(self, user, operator, name):
        self._check_management_access('create')
        slot = self._get_website_build_slot(operator, name)
        try:
            with self.env.cr.savepoint():
                domain = self.env['saas.domain.name'].create({'name': slot['host'], 'operator_id': operator.id})
                return self.create({
                    'name': slot['database_name'], 'operator_id': operator.id,
                    'admin_user': user.id, 'domain_name_id': domain.id,
                })
        except UniqueViolation as error:
            if error.diag.constraint_name not in ('saas_domain_name_name_unique', 'saas_db_name_operator_unique'):
                raise
            raise ValidationError(self.env._('This subdomain is already in use.')) from None

    def read_values_from_build(self):
        vals = super(SaasDb, self).read_values_from_build()

        if not self.is_admin_user_language_installed and self.admin_user.database_lang:
            installed_langs = [code for code, _ in self.execute_kw("res.lang", "get_installed")]

            if self.admin_user.database_lang in installed_langs:
                # language is installed
                vals.update(is_admin_user_language_installed=True)

        return vals

    def write_values_to_build(self):
        super(SaasDb, self).write_values_to_build()

        web_base_url = self.env["ir.config_parameter"].sudo().get_str("web.base.url")
        if not web_base_url:
            return

        if not self.is_admin_user_language_installed and self.admin_user.database_lang:
            # language is not installed. Installing
            try:
                # TODO: if something wents wrong - handle it more correctly than try catch
                wizard_id = self.execute_kw("base.language.install", "create", {"lang": self.admin_user.database_lang, "overwrite": False})
                if wizard_id:
                    # TODO: check if result is successfull1
                    self.execute_kw("base.language.install", "lang_install", wizard_id)

                    model, res_id = self.xmlid_lookup("base.user_admin")

                    self.execute_kw(model, "write", [res_id], {"lang": self.admin_user.database_lang})

            except Exception:
                _logger.exception("Something went wrong")
                pass

        self.execute_kw(
            "ir.config_parameter",
            "set_str",
            "database_expiration_details_link",
            web_base_url + self.access_url + "/renew_subscription",
        )

        self.execute_kw(
            "ir.config_parameter",
            "set_str",
            "database_expiration_details_link_label",
            "Renew subscribtion",
        )

        Config = self.env["ir.config_parameter"].sudo()

        database_expiration_warning_delay = Config.get_str("saas_apps_signup.database_expiration_warning_delay")
        if database_expiration_warning_delay:
            self.execute_kw(
                "ir.config_parameter",
                "set_str",
                "database_expiration_warning_delay",
                database_expiration_warning_delay
            )

    def _prepare_predecessor_build_vals(self, successor_build):
        res = super(SaasDb, self)._prepare_predecessor_build_vals(successor_build)
        res.update(
            contract_id=False,
        )
        return res

    def _prepare_successor_build_vals(self, predecessor_build):
        res = super(SaasDb, self)._prepare_successor_build_vals(predecessor_build)
        res.update(
            contract_id=predecessor_build.contract_id.id,
        )
        return res
