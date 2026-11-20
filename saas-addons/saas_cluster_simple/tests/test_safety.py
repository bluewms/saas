from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import tempfile
from unittest.mock import patch

from odoo.addons.base.tests.common import BaseCommon
from odoo.addons.host2db import override as host_module
from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .. import main as cluster


@tagged('post_install', '-at_install')
class TestClusterSafety(BaseCommon):
    def setUp(self):
        super().setUp()
        self.backup_dir = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(cluster, 'BACKUP_DIR', self.backup_dir))

    def test_backup_paths_cannot_escape_directory(self):
        for name in ('../outside.zip', '/tmp/outside.zip', '..\\outside.zip', 'bad\x00.zip'):
            with self.subTest(name=name), self.assertRaises(UserError):
                cluster.full_backup_path(name)
        outside = Path(self.backup_dir).parent / 'outside-saas-backup.zip'
        (Path(self.backup_dir) / 'link.zip').symlink_to(outside)
        with self.assertRaises(UserError):
            cluster.full_backup_path('link.zip')

    def test_failed_backup_is_not_published(self):
        def failing_dump(db_name, backup_file, **kwargs):
            backup_file.write(b'partial backup')
            raise OSError('simulated dump failure')

        with patch.object(cluster.db, 'dump', side_effect=failing_dump), self.assertRaises(OSError):
            cluster.create_backup('tenant_one')
        self.assertEqual(list(Path(self.backup_dir).iterdir()), [])

    def test_concurrent_backup_names_are_distinct(self):
        def dump(db_name, backup_file, **kwargs):
            backup_file.write(b'complete backup')

        with patch.object(cluster.db, 'dump', side_effect=dump):
            first = cluster.create_backup('tenant_one')['name']
            second = cluster.create_backup('tenant_one')['name']
        self.assertNotEqual(first, second)
        self.assertEqual(Path(cluster.full_backup_path(first)).read_bytes(), b'complete backup')
        self.assertEqual(Path(cluster.full_backup_path(first)).stat().st_mode & 0o777, 0o600)

    def test_restore_preserves_database_name_with_underscores(self):
        name = 'customer_one_2026-11-17_12_00_00.zip'
        Path(cluster.full_backup_path(name)).write_bytes(b'backup')
        with patch.object(cluster.db, 'exist', return_value=False), patch.object(cluster.db, 'restore') as restore:
            result = cluster.deploy_backup(name)
        self.assertTrue(result['db_name'].startswith('customer_one_'))
        self.assertLessEqual(len(result['db_name']), 63)
        restore.assert_called_once_with(result['db_name'], cluster.full_backup_path(name), copy=True)

    def test_restore_name_fits_postgresql_limit(self):
        with patch.object(cluster.db, 'exist', return_value=False):
            name = cluster._get_new_database_name('a' * 63)
        self.assertLessEqual(len(name), 63)

    def test_system_database_names_are_rejected(self):
        for name in ('postgres', 'template0', 'template1', '../tenant', 'a' * 64):
            with self.subTest(name=name), self.assertRaises(UserError):
                cluster.validate_database_name(name)

    def test_missing_requested_module_does_not_silently_succeed(self):
        @contextmanager
        def test_cursor(db_name):
            yield self.env.cr

        with patch.object(cluster, 'build_cursor', test_cursor):
            with self.assertRaisesRegex(UserError, 'missing_saas_test_module'):
                cluster.install_modules(self.env.cr.dbname, [('name', 'in', ['missing_saas_test_module'])])


@tagged('post_install', '-at_install')
class TestHostMappings(BaseCommon):
    def setUp(self):
        super().setUp()
        temporary_dir = self.enterContext(tempfile.TemporaryDirectory())
        filename = str(Path(temporary_dir) / 'host2db.ini')

        class TestConfig(host_module.Host2DBConfig):
            @property
            def config_filename(self):
                return filename

        self.writer = TestConfig()
        self.reader = TestConfig()

    def test_deleted_mapping_disappears_in_other_worker(self):
        self.writer.assign_host_to_db('customer.example.com', 'tenant_one')
        self.assertEqual(self.reader.get_db_by_host('customer.example.com'), 'tenant_one')
        self.writer.unassign_host('customer.example.com')
        self.assertIsNone(self.reader.get_db_by_host('customer.example.com'))

    def test_workers_do_not_overwrite_each_others_mappings(self):
        self.writer.assign_host_to_db('first.example.com', 'tenant_one')
        self.reader.assign_host_to_db('second.example.com', 'tenant_two')
        self.assertEqual(self.writer.get_db_by_host('first.example.com'), 'tenant_one')
        self.assertEqual(self.writer.get_db_by_host('second.example.com'), 'tenant_two')

    def test_parallel_updates_keep_all_mappings(self):
        def assign(index):
            config = self.writer if index % 2 else self.reader
            config.assign_host_to_db('customer%d.example.com' % index, 'tenant_%d' % index)

        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(assign, range(20)))
        for index in range(20):
            self.assertEqual(self.reader.get_db_by_host('customer%d.example.com' % index), 'tenant_%d' % index)

    def test_host_is_normalized_and_mapping_stays_inside_candidate_databases(self):
        self.writer.assign_host_to_db('Customer.EXAMPLE.com.', 'tenant_one')
        with patch.object(host_module, 'host2db_config', self.reader):
            self.assertEqual(host_module.db_filter(['tenant_one'], 'CUSTOMER.example.com:8069'), ['tenant_one'])
            self.assertEqual(host_module.db_filter(['other_tenant'], 'customer.example.com'), [])
            self.assertEqual(host_module.db_filter(['tenant_one'], 'attacker@customer.example.com'), [])
