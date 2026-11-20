#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
runtime=.saas-dev
commerce=${SAAS_DEV_COMMERCE:-0}

compose() {
    if [ "$commerce" = 1 ]; then
        set -- -f compose.commerce.dev.yaml "$@"
    fi
    docker compose --env-file "$runtime/.env" -f compose.dev.yaml "$@"
}

if [ "${1:-}" = init ]; then
    queue_addons=${SAAS_QUEUE_ADDONS:-../oca-queue}
    if [ ! -f "$queue_addons/queue_job/__manifest__.py" ]; then
        printf 'queue_job not found in %s\n' "$queue_addons" >&2
        exit 1
    fi

    mkdir -p "$runtime"
    if [ ! -f "$runtime/.env" ]; then
        (umask 077; python3 - "$runtime/.env" <<'PY'
import secrets
import sys

with open(sys.argv[1], 'x') as credentials:
    for instance in ('MASTER', 'CLIENT'):
        for setting in ('DB_PASSWORD', 'ADMIN_PASSWD'):
            credentials.write(f'SAAS_{instance}_{setting}={secrets.token_hex(24)}\n')
PY
        )
    fi

    python3 - "$commerce" <<'PY' > "$runtime/requirements.txt"
import json
import sys

with open('dependencies.lock.json') as lock_file:
    for dependency in json.load(lock_file)['python']:
        if dependency.get('commerce') and sys.argv[1] != '1':
            continue
        print(f"{dependency['package']}=={dependency['version']} --hash=sha256:{dependency['sha256']}")
PY
    if ! cmp -s "$runtime/requirements.txt" "$runtime/python-deps/requirements.lock"; then
        python3 -m pip install --disable-pip-version-check --no-deps --require-hashes \
            --target "$runtime/python-deps" --upgrade -r "$runtime/requirements.txt"
        cp "$runtime/requirements.txt" "$runtime/python-deps/requirements.lock"
    fi

    master_modules=saas,saas_portal,saas_operator_remote,saas_installed_apps,saas_access_apps,saas_database_limit,saas_apps
    if [ "$commerce" = 1 ]; then
        master_modules="$master_modules,saas_apps_signup"
    fi
    compose stop master client
    compose run --rm master --init="$master_modules" --without-demo --stop-after-init
    compose run --rm client --init=web,saas_cluster_simple --without-demo --stop-after-init
    set -- up -d --wait
fi

if [ ! -f "$runtime/.env" ]; then
    printf 'Initialize the environment with scripts/saas-dev.sh init\n' >&2
    exit 1
fi

compose "$@"
