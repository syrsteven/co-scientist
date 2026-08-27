"""Canonical identifiers accepted at durable Run boundaries."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator

MAX_RUN_ID_LENGTH = 128
_SAFE_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def validate_run_id(value: str) -> str:
    """Return one filesystem-safe, bounded Run identifier or fail closed."""

    if (
        len(value) > MAX_RUN_ID_LENGTH
        or _SAFE_RUN_ID.fullmatch(value) is None
        or ".." in value
    ):
        raise ValueError(
            "run_id must be a safe identifier of 1-128 ASCII letters, digits, '.', '_', "
            "or '-', starting with a letter or digit and without '..'"
        )
    return value


RunId = Annotated[str, AfterValidator(validate_run_id)]
