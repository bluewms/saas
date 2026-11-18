#!/usr/bin/env python3
"""Check addon syntax, manifest files, and Odoo 20 view modifiers."""

import argparse
import ast
import csv
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


def check_repository(root, addon_paths=(), strict_dependencies=False):
    errors = []
    manifests = {}
    for path in sorted(root.glob('*/__manifest__.py')):
        try:
            manifests[path.parent.name] = ast.literal_eval(path.read_text(encoding='utf-8'))
        except (SyntaxError, ValueError) as error:
            errors.append('%s: %s' % (path.relative_to(root), error))
    available = set(manifests)
    for addon_path in addon_paths:
        available.update(path.parent.name for path in addon_path.glob('*/__manifest__.py'))
    missing = set()
    for name, manifest in manifests.items():
        if not manifest.get('name') or not manifest.get('version', '').startswith('20.0.'):
            errors.append('%s: missing name or Odoo 20 version' % name)
        for filename in manifest.get('data', []) + manifest.get('demo', []):
            if not (root / name / filename).is_file():
                errors.append('%s: missing manifest file %s' % (name, filename))
        for entries in manifest.get('assets', {}).values():
            for entry in entries:
                if isinstance(entry, str) and entry.startswith(name + '/') and not list(root.glob(entry)):
                    errors.append('%s: missing asset %s' % (name, entry))
        if manifest.get('installable', True):
            missing.update(dependency for dependency in manifest.get('depends', []) if dependency not in available)
        for filename in manifest.get('data', []):
            if filename.endswith('/ir.access.csv') and (root / name / filename).is_file():
                with (root / name / filename).open(encoding='utf-8', newline='') as access_file:
                    for row in csv.DictReader(access_file):
                        if not row.get('operation') or set(row['operation']) - set('crud'):
                            errors.append('%s: invalid access operation' % filename)
    for name in manifests:
        for path in (root / name).rglob('*.py'):
            try:
                ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            except SyntaxError as error:
                errors.append('%s:%s: %s' % (path.relative_to(root), error.lineno, error.msg))
        for path in (root / name).rglob('*.xml'):
            try:
                tree = ET.parse(path)
            except ET.ParseError as error:
                errors.append('%s: %s' % (path.relative_to(root), error))
                continue
            for element in tree.iter():
                for attribute in ('invisible', 'readonly', 'required', 'column_invisible'):
                    value = element.get(attribute)
                    if value and value.strip().startswith('['):
                        errors.append('%s: %s must be a Python boolean expression' % (path.relative_to(root), attribute))
    if strict_dependencies and missing:
        errors.append('Missing addon dependencies: ' + ', '.join(sorted(missing)))
    return errors, missing, len(manifests)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--addons-path', action='append', default=[], help='Additional addon directories, comma separated')
    parser.add_argument('--strict-dependencies', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    addon_paths = [Path(value).expanduser() for entry in args.addons_path for value in entry.split(',')]
    errors, missing, count = check_repository(root, addon_paths, args.strict_dependencies)
    for error in errors:
        print('ERROR: ' + error, file=sys.stderr)
    if errors:
        return 1
    print('Checked %d addon manifests, Python files, XML, assets, and access data.' % count)
    if missing:
        print('External addons to supply: ' + ', '.join(sorted(missing)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
