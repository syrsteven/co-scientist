#!/bin/sh
# Starts the local service; a new database has no authorized runs and sends nothing.
# Existing explicitly started running research resumes on restart, within frozen limits.
set -eu
cd "$(dirname "$0")/.."
PYTHON_BIN="${CO_SCIENTIST_PYTHON:-python}"
AUTO_DB="${CO_SCIENTIST_AUTO_DB:-/private/tmp/co-scientist-v6-automatic/runs/stage.sqlite}"
AUTO_PORT="${CO_SCIENTIST_AUTO_PORT:-8770}"
mkdir -p "$(dirname "$AUTO_DB")"
export PYTHONPATH="$(pwd)/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON_BIN" -m co_scientist_next.workspace --db "$AUTO_DB" --port "$AUTO_PORT" \
 --automatic-research --responsive --real-goal --public-literature \
 --reading-model-config docs/workbench/reading-model.json \
 --generation-responses-config docs/workbench/responses-model.json \
 --review-responses-config docs/workbench/responses-model.json \
 --allow-development-goal-policy --allow-development-review-policy \
 --credential-env OPENAI_API_KEY --allow-real-model-calls
