from unittest.mock import patch

from odoo.addons.base.tests.common import BaseCommon
from odoo.exceptions import AccessError, ValidationError
from odoo.models import get_public_method
from odoo.tests.common import HttpCase, new_test_user, tagged

from odoo.addons.saas_cluster_simple import main as cluster


@tagged('post_install', '-at_install')
class TestSaasSecurity(BaseCommon):
    _test_user_groups = ('base.group_user', 'saas.group_user')

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.operator = cls.env['saas.operator'].sudo().create({
            'name': 'Security test operator', 'type': 'local',
            'global_url': 'https://master.example.com',
            'db_url_template': 'https://{db_name}.example.com',
        })
        build_vals = {'name': 'saas-security-tenant', 'operator_id': cls.operator.id}
        if 'max_users_limit' in cls.env['saas.db']._fields:
            build_vals['max_users_limit'] = 1
        cls.build = cls.env['saas.db'].sudo().create(build_vals)
        cls.manager = new_test_user(cls.env, login='saas_security_manager', groups='base.group_user,saas.group_manager')

    def test_cross_database_helpers_are_not_rpc_methods(self):
        methods = {
            'saas.db': ('create_db', 'drop_db', 'execute_kw', 'xmlid_lookup', 'xmlid_to_res_model_res_id', 'refresh_data', 'write_values_to_build', 'read_values_from_build'),
            'saas.operator': ('build_execute_kw', 'build_post_init', 'install_modules', 'post_init', 'map_domain', 'unmap_domain'),
            'saas.template.operator': ('create_db', 'preparing_template_next'),
            'saas.log': ('log_db_created', 'log_db_dropped', 'log_db_authed'),
        }
        for model, names in methods.items():
            for name in names:
                with self.subTest(model=model, method=name), self.assertRaises(AccessError):
                    get_public_method(self.env[model], name)

    def test_read_only_user_cannot_drop_database_via_unlink(self):
        with patch.object(cluster, 'drop_db') as drop:
            with self.assertRaises(AccessError):
                self.build.unlink()
        drop.assert_not_called()

    def test_read_only_user_cannot_refresh_or_install_modules(self):
        with self.assertRaises(AccessError):
            self.build.action_refresh_data()
        with self.assertRaises(AccessError):
            self.build.action_install_missing_mandatory_modules()

    def test_operator_write_checks_access_before_propagation(self):
        with patch.object(cluster, 'execute_kw') as execute:
            with self.assertRaises(AccessError):
                self.operator.write({'global_url': 'https://changed.example.com'})
        execute.assert_not_called()

    def test_operator_counts_support_multiple_records(self):
        second = self.operator.sudo().copy({'name': 'Second security operator'})
        self.env['saas.db'].sudo().create({'name': 'saas-second-security-tenant', 'operator_id': second.id})
        operators = self.operator | second.with_env(self.env)
        self.assertEqual(operators.mapped('build_count'), [1, 1])

    def test_management_database_cannot_be_registered_as_tenant(self):
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.env['saas.db'].sudo().create({'name': self.env.cr.dbname, 'operator_id': self.operator.id})

    def test_tenant_registry_cannot_use_privileged_saas_helpers(self):
        with patch.dict('os.environ', {'SAAS_MASTER_DATABASE': 'other-management-db'}):
            with patch.object(cluster, 'drop_db') as drop, self.assertRaises(AccessError):
                self.build.sudo().drop_db()
            drop.assert_not_called()

    def test_build_stays_closed_until_finalization(self):
        build = self.build.sudo()
        with patch.object(cluster, 'create_db'), patch.object(type(build), 'refresh_data') as refresh:
            build.create_db(None, False)
            self.assertEqual(build.state, 'creating')
            previous_calls = refresh.call_count
            build._finalize_build()
            self.assertEqual(build.state, 'done')
            self.assertEqual(refresh.call_count, previous_calls + 1)
            build._finalize_build()
            self.assertEqual(refresh.call_count, previous_calls + 1)

    def test_remote_password_has_field_access_control(self):
        if 'remote_master_pwd' not in self.operator._fields:
            self.skipTest('Remote operator addon is not installed')
        self.operator.sudo().write({'remote_master_pwd': 'isolated-test-secret'})
        self.assertNotIn('remote_master_pwd', self.operator.fields_get())
        with self.assertRaises(AccessError):
            self.operator.read(['remote_master_pwd'])

    def test_read_only_user_cannot_forge_backup_metadata(self):
        if 'saas.db.backup' not in self.env:
            self.skipTest('Backup addon is not installed')
        Backup = self.env['saas.db.backup']
        with self.assertRaises(AccessError):
            Backup.create({'origin_build_id': self.build.id, 'remote_filename': 'other-tenant.zip'})
        backup = Backup.sudo().create({'origin_build_id': self.build.id})
        with self.assertRaises(AccessError):
            backup.with_env(self.env).write({'remote_filename': 'other-tenant.zip'})

    def test_stale_domain_job_keeps_current_owner(self):
        if 'saas.domain.name' not in self.env:
            self.skipTest('Domain addon is not installed')
        Domain = self.env['saas.domain.name'].sudo()
        domain = Domain.create({'name': 'handover.example.com', 'operator_id': self.operator.id})
        first = self.build.sudo()
        second = first.copy({'name': 'saas-successor-security-tenant'})
        first.domain_name_id = domain
        first.domain_name_id = False
        second.domain_name_id = domain
        Operator = type(self.operator)
        with patch.object(Operator, 'map_domain') as assign, patch.object(Operator, 'unmap_domain') as remove:
            Domain._run_domain_operations(self.operator.id, [['unmap', domain.name]])
        assign.assert_called_once_with(domain.name, second.name)
        remove.assert_not_called()

    def test_assigned_domain_cannot_change_operator(self):
        if 'saas.domain.name' not in self.env:
            self.skipTest('Domain addon is not installed')
        domain = self.env['saas.domain.name'].sudo().create({
            'name': 'operator-check.example.com', 'operator_id': self.operator.id,
        })
        self.build.sudo().domain_name_id = domain
        other = self.operator.sudo().copy({'name': 'Other domain operator'})
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            domain.operator_id = other

    def test_pending_job_counter_reads_queue_records(self):
        if 'number_of_queue_jobs_to_be_done' not in self.build._fields:
            self.skipTest('Portal addon is not installed')
        build = self.build.with_user(self.manager)
        build.with_delay().create_db(None, False)
        self.assertEqual(build.number_of_queue_jobs_to_be_done, 1)

    def test_login_uses_verified_owner_and_canonical_admin_id(self):
        if 'admin_user' not in self.build._fields:
            self.skipTest('Build administrator addon is not installed')
        owner = new_test_user(self.env, login='saas_token_owner', groups='base.group_portal')
        other = new_test_user(self.env, login='saas_token_other', groups='base.group_portal')
        tenant = self.env['saas.db'].sudo().create({
            'name': 'saas-token-owned-tenant', 'operator_id': self.operator.id,
            'admin_user': owner.id, 'state': 'done', 'max_users_limit': 1,
        })
        Token = self.env['auth_quick_master.token']
        with patch.object(cluster, 'execute_kw', return_value=('res.users', 42)):
            values = Token.with_user(owner)._prepare_token_values(tenant.id, 1, 'attacker-login')
        self.assertEqual(values['user_id'], owner.id)
        self.assertEqual(values['build_user_id'], 42)
        self.assertFalse(values['build_login'])
        with self.assertRaises(AccessError):
            Token.with_user(other)._prepare_token_values(tenant.id, 1, 'attacker-login')


@tagged('post_install', '-at_install')
class TestSaasTokenAudience(HttpCase):
    def test_token_cannot_be_redeemed_by_another_build(self):
        owner = new_test_user(self.env, login='audience_test_owner', groups='base.group_portal')
        operator = self.env['saas.operator'].sudo().create({
            'name': 'Audience test operator', 'type': 'local',
            'global_url': 'https://master.example.com', 'db_url_template': 'https://{db_name}.example.com',
        })
        build = self.env['saas.db'].sudo().create({
            'name': 'saas-audience-test-tenant', 'operator_id': operator.id,
            'admin_user': owner.id, 'state': 'done', 'max_users_limit': 1,
        })
        token = self.env['auth_quick_master.token'].sudo().create({
            'user_id': owner.id, 'build': str(build.id), 'build_user_id': 42,
        }).token

        def check(reference):
            response = self.url_open('/auth_quick_master/check-token', json=self.build_rpc_payload({
                'token': token, 'build': reference,
            }))
            self.assertEqual(response.status_code, 200)
            return response.json()['result']

        self.assertEqual(check(None), {'error': 'Invalid build reference'})
        self.assertEqual(check('other-build'), {'error': 'Invalid build reference'})
        self.assertEqual(check(str(build.id)), {
            'success': 'ok', 'data': {'build_user_id': 42, 'build_login': False, 'build': str(build.id)},
        })
        self.assertEqual(check(str(build.id)), {'error': 'Invalid token'})
