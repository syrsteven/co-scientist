"""Explicit install-time asset acquisition; runtime never downloads assets."""

import hashlib
import os
from importlib.resources import files
from pathlib import Path

ASSETS = {
    "deepseek-v41.json": "81f64d1248a68ce3663e07ab3ee48b851e5df0e32d27cb98e4c9a268151e8d99",
    "o200k_base.tiktoken": "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d",
}
OPENAI_URL = "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken"


def asset_dir():
    return Path(
        os.environ.get(
            "CO_SCIENTIST_RESOURCE_DIR", str(Path.home() / ".cache/co-scientist/resources-v1")
        )
    )


def package_file(name):
    return Path(str(files("co_scientist.release").joinpath("resources", name)))


def resource_path(value):
    if not value.startswith("resource:"):
        return Path(value)  # Legacy explicit paths are unchanged.
    name = value.removeprefix("resource:")
    if name not in ASSETS:
        raise ValueError("unknown versioned tokenizer resource")
    path = package_file(name) if name == "deepseek-v41.json" else asset_dir() / name
    if not path.is_file():
        raise ValueError(
            "tokenizer missing; run co-scientist ideation resources before creating a Run"
        )
    if hashlib.sha256(path.read_bytes()).hexdigest() != ASSETS[name]:
        raise ValueError("TOKENIZER_IDENTITY_MISMATCH")
    return path


def install_openai_asset(source=None):
    """Only this explicit setup command may download the public tokenizer file.

    Distribution of this separate hosted data asset is not assumed from the
    tiktoken code license. Source/wheel therefore ship its URL and hash only.
    """
    import urllib.request

    target = asset_dir() / "o200k_base.tiktoken"
    if target.exists():
        resource_path("resource:o200k_base.tiktoken")
        return str(target)
    if source is not None:
        data = Path(source).read_bytes()
    else:
        with urllib.request.urlopen(OPENAI_URL, timeout=60) as response:
            data = response.read(8_000_001)
    if len(data) > 8_000_000 or hashlib.sha256(data).hexdigest() != ASSETS[target.name]:
        raise ValueError("downloaded tokenizer hash/capacity mismatch")
    target.parent.mkdir(parents=True, exist_ok=True)
    # No overwrite, and no runtime fetch; bytes are verified before placement.
    with target.open("xb") as handle:
        handle.write(data)
    return str(target)
