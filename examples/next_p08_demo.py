"""Checkout-only, explicitly INVENTED offline engineering demo; never a real study."""

import argparse
import runpy
from pathlib import Path

from co_scientist_next.store import Store

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--db", required=True)
args = parser.parse_args()
path = Path(args.db).resolve()
if path.exists():
    parser.error("Use a new demo DB path; existing data will not be modified")
helpers = runpy.run_path(str(Path(__file__).resolve().parents[1] / "tests/next/test_generation.py"))
with Store(path) as store:
    run, _, _ = helpers["prepared"](store)
    project = store.run(run)["project_id"]
print("INVENTED OFFLINE ENGINEERING FIXTURES; science_validated=false")
print("Project:", project, "Run:", run)
print("No P08 generated yet. Start the page with:")
print(
    "PYTHONPATH=src python -m co_scientist_next.workspace --db",
    path,
    "--development-test --development-reading --development-generation",
)
