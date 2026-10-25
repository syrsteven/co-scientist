#!/bin/sh
# Install dependencies + verified tokenizer at setup time, never at Run time.
set -eu
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
            echo 'Installs into the current Python environment (Python 3.11/3.12).'
            echo 'Activate your environment first; PYTHON optionally selects an interpreter.'
            exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done
install_python=$(command -v "${PYTHON:-python}") || {
    echo 'Python not found. Activate a Python 3.11/3.12 environment or set PYTHON.' >&2
    exit 2
}
case "$install_python" in
    /*) ;;
    *) install_python="$(pwd)/$install_python" ;;
esac
"$install_python" -c 'import sys; (3,11) <= sys.version_info[:2] < (3,13) or sys.exit("Python 3.11/3.12 required"); print("Installing into:", sys.executable)'
"$install_python" -m pip --version >/dev/null || {
    echo 'pip is required in the selected Python environment.' >&2
    exit 2
}
if [ -n "$asset" ]; then
    case "$asset" in
        /*) ;;
        *) asset="$(pwd)/$asset" ;;
    esac
    [ -f "$asset" ] && [ -r "$asset" ] || {
        echo 'Tokenizer file must exist and be readable.' >&2
        exit 2
    }
fi
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
"$install_python" -m pip install --no-user -c constraints.lock setuptools wheel
"$install_python" -m pip install --no-user --no-build-isolation -c constraints.lock ".[${mode}]"
"$install_python" -m pip check
if [ -n "$asset" ]; then
    "$install_python" -c 'from co_scientist.release.cli import main; main()' ideation resources --from-file "$asset"
else
    "$install_python" -c 'from co_scientist.release.cli import main; main()' ideation resources
fi
echo 'Ready. Start: co-scientist-web'
