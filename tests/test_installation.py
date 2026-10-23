"""Installation/documentation contracts; no network or scientific dispatch."""

import re
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_single_constraints_covers_all_direct_dependencies():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    constraints = {
        line.split("==")[0].lower().replace("_", "-")
        for line in (ROOT / "constraints.lock").read_text().splitlines()
        if "==" in line and not line.startswith("#")
    }
    deps = list(project["dependencies"])
    for values in project["optional-dependencies"].values():
        deps.extend(values)
    for dependency in deps:
        name = re.split(r"[<>=\[]", dependency)[0].lower().replace("_", "-")
        assert name in constraints, dependency
    assert not (ROOT / "requirements.lock").exists()
    assert not (ROOT / "requirements-web.lock").exists()


def test_version_has_one_authoritative_source():
    from co_scientist import __version__

    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert "version" in metadata["project"]["dynamic"]
    assert metadata["tool"]["setuptools"]["dynamic"]["version"]["attr"] == "co_scientist.__version__"
    assert re.fullmatch(r"\d+\.\d+\.\d+\.dev\d+", __version__)


def test_setup_help_does_not_install_or_download():
    result = subprocess.run(
        ["sh", str(ROOT / "scripts/setup.sh"), "--help"],
        capture_output=True, text=True, check=True,
    )
    assert "--dev" in result.stdout and "--tokenizer-file" in result.stdout


def test_readme_local_links_and_current_web_documentation():
    readme = (ROOT / "README.md").read_text()
    for relative in re.findall(r"\]\((docs/[^)#]+)(?:#[^)]*)?\)", readme):
        assert (ROOT / relative).is_file(), relative
    assert "sh scripts/setup.sh" in readme
    assert "co-scientist-web" in readme
    assert "没有已上线 HTTP" not in (ROOT / "docs/FRONTEND_INTEGRATION.md").read_text()
    assert "0.1.0-py3" not in (ROOT / "docs/DEPLOYMENT_GUIDE_ZH.md").read_text()
