"""Fresh processes must not depend on pytest's prior application imports."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize("first", [
    "from co_scientist.runtime.core_runner import CoreRunner",
    "from co_scientist.application import ApplicationService",
    "from co_scientist.application.config import resolve_run_config",
])
def test_runtime_and_application_import_independently(first: str) -> None:
    subprocess.run([
        sys.executable, "-c", first + "\n"
        "from co_scientist.runtime.core_runner import CoreRunner\n"
        "from co_scientist.application import ApplicationService\n"
        "assert CoreRunner.__name__ == 'CoreRunner'\n"
        "assert ApplicationService.__name__ == 'ApplicationService'\n",
    ], check=True, capture_output=True, text=True, timeout=15)
