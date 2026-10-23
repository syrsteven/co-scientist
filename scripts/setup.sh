#!/bin/sh
# Install dependencies + verified tokenizer at setup time, never at Run time.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
mode=web
asset=
while [ "$#" -gt 0 ]; do
    case "$1" in
        --dev) mode=web,dev,web-test; shift ;;
        --tokenizer-file)
            [ "$#" -ge 2 ] || { echo 'Missing tokenizer file' >&2; exit 2; }
            asset=$2; shift 2 ;;
        --help)
            echo 'Usage: sh scripts/setup.sh [--dev] [--tokenizer-file /absolute/path/o200k_base.tiktoken]'
            echo 'PYTHON selects Python 3.11/3.12; VENV selects the virtual environment directory.'
            exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done
bootstrap_python=${PYTHON:-python3}
venv=${VENV:-.venv}
"$bootstrap_python" -c 'import sys; assert (3,11) <= sys.version_info[:2] < (3,13), "Python 3.11/3.12 required"'
if [ ! -e "$venv" ]; then
    "$bootstrap_python" -m venv "$venv"
fi
"$venv/bin/python" -c 'import sys; assert sys.prefix != sys.base_prefix; assert (3,11) <= sys.version_info[:2] < (3,13)'
"$venv/bin/python" -m pip install -c constraints.lock setuptools wheel
"$venv/bin/python" -m pip install --no-build-isolation -c constraints.lock ".[${mode}]"
"$venv/bin/python" -m pip check
if [ -n "$asset" ]; then
    "$venv/bin/co-scientist" ideation resources --from-file "$asset"
else
    "$venv/bin/co-scientist" ideation resources
fi
echo "Ready. Start: $venv/bin/co-scientist-web"
