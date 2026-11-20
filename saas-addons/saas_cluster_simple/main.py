# Copyright 2018 Ivan Yelizariev <https://github.com/yelizariev>
# Copyright 2019 Denis Mudarisov <https://github.com/trojikman>
# Copyright 2020-2021 Eugene Molotov <https://github.com/em230418>
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime
import logging
import os
import re
import secrets
import tempfile
import threading

from odoo import SUPERUSER_ID, api, fields, tools
from odoo.exceptions import UserError
from odoo.http import request_var
from odoo.models import BaseModel
from odoo.modules import db
from odoo.modules import module as odoo_module
from odoo.modules.registry import Registry
from odoo.service.model import _traverse_containers
from odoo.tools import lazy

from odoo.addons.host2db import host2db_config

_logger = logging.getLogger(__name__)
BACKUP_DIR = tools.config["data_dir"] + "/backups"

# Captured at import time, before the test framework patches Registry.new.
_REAL_REGISTRY_NEW = Registry.new
_TEST_GUARD_LOCK = threading.RLock()


def validate_database_name(db_name):
    if (
        not isinstance(db_name, str)
        or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,62}", db_name)
        or db_name.lower() in {"postgres", "template0", "template1"}
    ):
        raise UserError("Invalid tenant database name.")
    return db_name


def full_backup_path(backup_name):
    if (
        not isinstance(backup_name, str)
        or not backup_name
        or os.path.basename(backup_name) != backup_name
        or "\\" in backup_name
        or "\x00" in backup_name
        or not backup_name.endswith(".zip")
    ):
        raise UserError("Invalid backup filename.")
    root = os.path.realpath(BACKUP_DIR)
    path = os.path.join(root, backup_name)
    if os.path.commonpath([root, os.path.realpath(path)]) != root or os.path.islink(path):
        raise UserError("Backup path is outside the backup directory.")
    return path


__all__ = [
    "create_db",
    "drop_db",
    "install_modules",
    "post_init",
    "map_domain",
    "unmap_domain",
    "execute_kw",
    "create_backup",
    "deploy_backup",
    "signal_changes",
]


@contextmanager
def turn_off_tests():
    """Lift Odoo 20's test guards around operations on other databases.

    While a test runs, Registry.new is patched to raise and
    ir_module._button_immediate_function refuses to work when
    odoo.modules.module.current_test is set. Neither applies to what a SaaS
    operator legitimately does here: create and provision template/build
    databases, which are separate databases and separate cursors.
    """
    if not tools.config["test_enable"] and not odoo_module.current_test:
        yield
        return

    # The configuration and registry factory are process globals. Serialize
    # test-only changes and leave production workers completely untouched.
    with _TEST_GUARD_LOCK:
        with _turn_off_tests():
            yield


@contextmanager
def _turn_off_tests():
    test_enable = tools.config["test_enable"]
    current_test = odoo_module.current_test
    registry_new = Registry.new
    tools.config["test_enable"] = {}
    odoo_module.current_test = None
    Registry.new = _REAL_REGISTRY_NEW
    try:
        yield
    finally:
        Registry.new = registry_new
        odoo_module.current_test = current_test
        tools.config["test_enable"] = test_enable
        if test_enable:
            # Odoo's shutdown summary walks every loaded registry and expects a
            # test report on it, but the registries built above have none,
            # because they were loaded with tests off.
            from odoo.tests.result import OdooTestResult

            for registry in list(Registry.registries.values()):
                if registry._assertion_report is None:
                    registry._assertion_report = OdooTestResult()


@contextmanager
def build_cursor(db_name):
    """Cursor on a template/build database, whose registry is loaded on demand.

    The guards stay lifted while the cursor closes: committing a transaction
    that invalidated the registry rebuilds it right there.
    """
    validate_database_name(db_name)
    thread = threading.current_thread()
    previous_dbname = getattr(thread, "dbname", None)
    request_token = request_var.set(None)
    thread.dbname = db_name
    try:
        with turn_off_tests():
            registry = Registry(db_name)
            with registry.cursor() as cr:
                yield cr
    finally:
        request_var.reset(request_token)
        thread.dbname = previous_dbname


def create_db(template_db, db_name, demo, lang="en_US", admin_password=None, **kw):
    validate_database_name(db_name)
    if template_db:
        validate_database_name(template_db)
    # to avoid installing extra modules we need this condition
    initial_modules = tools.config["init"]
    tools.config["init"] = {}
    try:
        with turn_off_tests():
            if template_db:
                db.duplicate(template_db, db_name)
            else:
                db.create(
                    db_name,
                    demo=bool(demo),
                    user_password=admin_password or secrets.token_urlsafe(32),
                    lang=lang,
                )
    finally:
        tools.config["init"] = initial_modules


def drop_db(db_name):
    validate_database_name(db_name)
    # Odoo 20 replaced db.exp_drop (which ignored missing databases) by
    # db.drop, that raises.
    if db.exist(db_name):
        db.drop(db_name)


def install_modules(db_name, modules):
    # The guards stay lifted while the cursor closes: committing a transaction
    # that changed the registry builds the new registry right there.
    with build_cursor(db_name) as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})

        # We need to have fresh module list before installing new ones
        env["ir.module.module"].update_list()

        module_domain = fields.Domain(modules)
        requested_names = set()
        for condition in module_domain.iter_conditions():
            if condition.field_expr == 'name' and condition.operator == 'in':
                requested_names.update(condition.value)
        available = env['ir.module.module'].search([('name', 'in', sorted(requested_names))])
        unavailable = requested_names - set(available.filtered(lambda module: module.state != 'uninstallable').mapped('name'))
        if unavailable:
            raise UserError(env._('Modules are not available on this operator: %s', sorted(unavailable)))

        module_ids = env["ir.module.module"].search(
            fields.Domain("state", "=", "uninstalled") & module_domain
        )
        module_ids.button_immediate_install()

        # Some magic to force reloading registry in other workers: the commit
        # performed when leaving this cursor signals the registry change.
        env.transaction.will_change_registry()

def post_init(db_name, template_post_init):
    with build_cursor(db_name) as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})
        action = env["ir.actions.server"].create(
            {
                "name": "Local Code Eval",
                "state": "code",
                "model_id": 1,
                "code": template_post_init,
            }
        )
        action.run()
        action.unlink()


def map_domain(domain, db_name):
    validate_database_name(db_name)
    host2db_config.assign_host_to_db(domain, db_name)


def unmap_domain(domain):
    host2db_config.unassign_host(domain)


def execute_kw(db_name, model, method, args, kwargs):
    return execute(db_name, SUPERUSER_ID, model, method, *args, **kwargs)


def create_backup(db_name):
    validate_database_name(db_name)
    os.makedirs(BACKUP_DIR, mode=0o700, exist_ok=True)
    backup_name = "{}_{}_{}.zip".format(
        db_name, datetime.now().strftime("%Y-%m-%d_%H_%M_%S"), secrets.token_hex(8),
    )
    # Use a private temporary file in the confined data directory. Publish it
    # only after the dump succeeds, so failed backups cannot be restored.
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=BACKUP_DIR, prefix=".backup-", delete=False) as backup_file:
            temporary_path = backup_file.name
            db.dump(db_name, backup_file, backup_format="zip")
            backup_file.flush()
            os.fsync(backup_file.fileno())
        os.replace(temporary_path, full_backup_path(backup_name))
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)
    return {
        "name": backup_name,
    }


def remove_backup(backup_name):
    os.unlink(full_backup_path(backup_name))


def _get_new_database_name(old_db_name):
    validate_database_name(old_db_name)
    for _ in range(10):
        db_name = "{}_{}_{}".format(
            old_db_name[:43], datetime.now().strftime("%Y-%m-%d"), secrets.token_hex(4),
        )
        if not db.exist(db_name):
            return db_name


def deploy_backup(backup_name):
    backup_path = full_backup_path(backup_name)
    match = re.fullmatch(
        r"(.+)_\d{4}-\d{2}-\d{2}_\d{2}_\d{2}_\d{2}(?:_[0-9a-f]{16})?\.zip",
        backup_name,
    )
    if not match or not os.path.isfile(backup_path):
        raise UserError("Backup file is missing or its filename is invalid.")
    original_db_name = match.group(1)
    db_name = _get_new_database_name(original_db_name)
    if not db_name:
        raise Exception("Cannot calculate database name for deploying backup %s" % (backup_name,))

    db.restore(db_name, backup_path, copy=True)
    return {
        "db_name": db_name,
    }


def signal_changes(db_name):
    with build_cursor(db_name) as cr:
        # Odoo 20: cursors get their Transaction only via an Environment, and
        # registry signaling moved from Registry to Transaction.
        api.Environment(cr, SUPERUSER_ID, {}).transaction.will_change_registry()


# Modified version of odoo.service.model.execute_cr
# Removes checking private methods since
# cluster requires all methods to be executed
# It is expected, that master password check will protect
# from unauthorized usage
def execute(db, uid, obj, method, *args, **kw):
    with build_cursor(db) as cr:
        env = api.Environment(cr, uid, {})
        env.transaction.default_env = env
        recs = env.get(obj)
        if recs is None:
            raise UserError("Object %s doesn't exist" % obj)

        model_method = getattr(type(recs), method)
        context = kw.pop("context", None) or {}
        if getattr(model_method, "_api_model", False):
            # @api.model methods receive no ids
            targets = recs
        else:
            ids, args = args[0], args[1:]
            targets = recs.browse(ids)

        res = model_method(targets.with_context(context), *args, **kw)
        if method == "create":
            res = res.id if isinstance(args[0], Mapping) else res.ids
        elif isinstance(res, BaseModel):
            res = res.ids
        # evaluate lazy values before the cursor is closed
        for x in _traverse_containers(res, lazy):
            x._value
        if res is None:
            _logger.info('The method %s of the object %s can not return `None` !', method, obj)
        return res
