import configparser
from contextlib import contextmanager
import fcntl
import ipaddress
import logging
import os
import re
import tempfile
import threading
from urllib.parse import urlsplit

from odoo import http
from odoo.tools import config


def normalize_domain(domain):
    if not isinstance(domain, str):
        raise ValueError('Invalid domain name')
    domain = domain.strip().rstrip('.').lower()
    try:
        domain = domain.encode('idna').decode('ascii')
    except UnicodeError as error:
        raise ValueError('Invalid domain name') from error
    if len(domain) > 253 or not all(
        re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
        for label in domain.split('.')
    ):
        raise ValueError('Invalid domain name')
    return domain


def normalize_host(host):
    if not isinstance(host, str) or not host or any(char.isspace() for char in host):
        raise ValueError('Invalid Host header')
    parsed = urlsplit('//' + host)
    if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ValueError('Invalid Host header')
    # Reading port validates it even though mappings are independent of ports.
    parsed.port
    if not parsed.hostname:
        raise ValueError('Invalid Host header')
    try:
        return str(ipaddress.ip_address(parsed.hostname))
    except ValueError:
        hostname = parsed.hostname.rstrip('.').lower()
        # Existing technical database names may use underscores in the default
        # URL template. Registration of custom domains remains strict.
        if len(hostname) <= 253 and all(
            re.fullmatch(r'[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?', label)
            for label in hostname.split('.')
        ):
            return hostname
        return normalize_domain(hostname)


class Host2DBConfig(configparser.ConfigParser):
    SECTION = "mappings"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('interpolation', None)
        super(Host2DBConfig, self).__init__(*args, **kwargs)
        self._lock = threading.RLock()
        self._signature = None
        with self._file_lock():
            self._reread_config()

    @property
    def config_filename(self):
        return os.path.join(config["data_dir"], "host2db.ini")

    def _file_signature(self):
        try:
            stat = os.stat(self.config_filename)
            return stat.st_ino, stat.st_mtime_ns, stat.st_size
        except FileNotFoundError:
            return None

    def _reread_config(self):
        # ConfigParser.read merges into existing values. Clear first so removed
        # mappings disappear from every worker as well.
        self.clear()
        super().read(self.config_filename, encoding='utf-8')
        if not self.has_section(self.SECTION):
            self.add_section(self.SECTION)
        self._signature = self._file_signature()

    @contextmanager
    def _file_lock(self):
        os.makedirs(os.path.dirname(self.config_filename), mode=0o700, exist_ok=True)
        descriptor = os.open(self.config_filename + '.lock', os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)

    def _save_config(self):
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8', dir=os.path.dirname(self.config_filename),
                prefix='.host2db-', delete=False,
            ) as config_file:
                temporary_path = config_file.name
                self.write(config_file)
                config_file.flush()
                os.fsync(config_file.fileno())
            os.replace(temporary_path, self.config_filename)
            self._signature = self._file_signature()
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def assign_host_to_db(self, host, db):
        host = normalize_domain(host)
        if not isinstance(db, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,62}', db):
            raise ValueError('Invalid database name')
        self.set(self.SECTION, host, db)

    def unassign_host(self, host):
        self.remove_option(self.SECTION, normalize_domain(host))

    def remove_option(self, section, option):
        with self._lock, self._file_lock():
            self._reread_config()
            res = super(Host2DBConfig, self).remove_option(section, option)
            try:
                self._save_config()
            except OSError:
                self._reread_config()
                raise
            return res

    def set(self, section, option, value=None):
        with self._lock, self._file_lock():
            self._reread_config()
            res = super(Host2DBConfig, self).set(section, option, value)
            try:
                self._save_config()
            except OSError:
                self._reread_config()
                raise
            return res

    def get_db_by_host(self, host):
        with self._lock:
            if self._file_signature() != self._signature:
                with self._file_lock():
                    self._reread_config()
            return self.get(self.SECTION, normalize_host(host), fallback=None)


db_filter_org = http.router.db_filter
host2db_config = Host2DBConfig()


def db_filter(dbs, host=None):
    host = host or http.request.httprequest.environ.get("HTTP_HOST", "")
    try:
        dbname = host2db_config.get_db_by_host(host)
    except ValueError:
        return []
    if dbname:
        return [dbname] if dbname in dbs else []
    else:
        return db_filter_org(dbs, host)


if "host2db" in (config.get("server_wide_modules") or []):
    _logger = logging.getLogger(__name__)
    _logger.info("monkey patching odoo.http.router.db_filter")
    http.router.db_filter = db_filter
