#!/bin/sh
# Does not send requests. Only explicit subsequent browser actions may send.
set -eu
cd "$(dirname "$0")/.."
PYTHON_BIN="${CO_SCIENTIST_PYTHON:-python}"
STAGE_DB="${CO_SCIENTIST_STAGE_DB:-/private/tmp/co-scientist-v6-stage/runs/stage.sqlite}"
STAGE_PORT="${CO_SCIENTIST_STAGE_PORT:-8767}"
mkdir -p "$(dirname "$STAGE_DB")"
set -- --db "$STAGE_DB" --port "$STAGE_PORT" --development-test \
 --require-goal-test-opt-in --responsive --public-literature \
 --reading-model-config docs/workbench/reading-model.json \
 --generation-responses-config docs/workbench/responses-model.json \
 --review-responses-config docs/workbench/responses-model.json \
 --allow-development-review-policy --credential-env OPENAI_API_KEY --allow-real-model-calls
if [ -n "${CO_SCIENTIST_HISTORY_DB:-}" ]; then
 set -- "$@" --history-db "$CO_SCIENTIST_HISTORY_DB"
fi
export PYTHONPATH="$(pwd)/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON_BIN" -m co_scientist_next.workspace "$@"
