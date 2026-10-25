"""Installation/documentation contracts; no network or scientific dispatch."""

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def setup_probe(tmp_path):
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts/setup.sh", project / "scripts/setup.sh")
    (project / "constraints.lock").write_text("# offline probe\n")
    active = tmp_path / "active environment"
    active.mkdir()
    interpreter = active / "python"
    interpreter.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "with open(os.environ['SETUP_PROBE_LOG'], 'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
        "if sys.argv[1:3] == ['-m', 'venv']: sys.exit('must not create an environment')\n"
        "if os.environ.get('SETUP_PROBE_PREFLIGHT') == 'version' and sys.argv[1] == '-c': sys.exit(3)\n"
        "if os.environ.get('SETUP_PROBE_PREFLIGHT') == 'pip' and sys.argv[1:4] == ['-m', 'pip', '--version']: sys.exit(19)\n"
        "if os.environ.get('SETUP_PROBE_FAIL') and sys.argv[1:3] == ['-m', 'pip'] and 'install' in sys.argv: sys.exit(17)\n"
    )
    interpreter.chmod(0o755)
    (active / "python3").symlink_to(interpreter)
    log = tmp_path / "calls.jsonl"
    environment = dict(os.environ, PATH=str(active) + os.pathsep + os.environ.get("PATH", ""),
                       SETUP_PROBE_LOG=str(log), PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
    environment.pop("PYTHON", None)
    environment.pop("SETUP_PROBE_FAIL", None)

    def run(*args, **overrides):
        result = subprocess.run(["sh", str(project / "scripts/setup.sh"), *args],
                                cwd=tmp_path, env={**environment, **overrides},
                                text=True, capture_output=True, check=False)
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, calls, project

    return run, interpreter, tmp_path


@pytest.mark.parametrize("dev", [False, True])
@pytest.mark.parametrize("environment_kind", ["conda", "venv", "other"])
def test_setup_uses_active_python_without_creating_environment(setup_probe, dev, environment_kind):
    run, _, folder = setup_probe
    hints = {"conda": {"CONDA_PREFIX": str(folder / "conda")},
             "venv": {"VIRTUAL_ENV": str(folder / "venv")}, "other": {}}
    result, calls, project = run(*(["--dev"] if dev else []), **hints[environment_kind])
    assert result.returncode == 0, result.stderr
    assert not (project / ".venv").exists()
    assert all(call[:2] != ["-m", "venv"] for call in calls)
    installs = [call for call in calls if call[:3] == ["-m", "pip", "install"]]
    assert len(installs) == 2
    assert all(call[call.index("-c") + 1] == "constraints.lock" for call in installs)
    assert all("--no-user" in call for call in installs)
    assert installs[1][-1] == (".[web,dev,web-test]" if dev else ".[web]")
    assert ["-m", "pip", "check"] in calls
    assert any(call[0] == "-c" and "co_scientist.release.cli" in call[1]
               and call[2:] == ["ideation", "resources"] for call in calls)
    assert "Ready. Start: co-scientist-web" in result.stdout


def test_setup_explicit_python_and_relative_tokenizer(setup_probe):
    run, interpreter, folder = setup_probe
    (folder / "tokenizer data").write_text("offline fixture")
    result, calls, _ = run("--tokenizer-file", "tokenizer data", PYTHON=str(interpreter))
    assert result.returncode == 0, result.stderr
    assert calls[-1][-2:] == ["--from-file", str(folder / "tokenizer data")]


def test_setup_stops_on_install_failure(setup_probe):
    run, _, _ = setup_probe
    result, calls, _ = run(SETUP_PROBE_FAIL="1")
    assert result.returncode == 17
    assert not any("resources" in call for call in calls)
    assert ["-m", "pip", "check"] not in calls
    assert "Ready." not in result.stdout


@pytest.mark.parametrize("args", [["--bad"], ["--tokenizer-file"], ["--tokenizer-file", "absent"]])
def test_setup_bad_arguments_have_no_install_side_effects(setup_probe, args):
    run, _, _ = setup_probe
    result, calls, _ = run(*args)
    assert result.returncode != 0
    assert not any(call[:3] == ["-m", "pip", "install"] for call in calls)


@pytest.mark.parametrize("failure", ["version", "pip"])
def test_setup_preflight_failure_never_installs(setup_probe, failure):
    run, _, _ = setup_probe
    result, calls, _ = run(SETUP_PROBE_PREFLIGHT=failure)
    assert result.returncode != 0
    assert not any(call[:3] == ["-m", "pip", "install"] for call in calls)


def test_user_docs_use_environment_independent_entrypoints():
    for name in ("README.md", "docs/DEPLOYMENT_GUIDE_ZH.md", "docs/ARCHITECTURE.md"):
        text = (ROOT / name).read_text()
        assert ".venv/bin/co-scientist" not in text
        assert ".venv/bin/python" not in text
    for name in ("README.md", "docs/DEPLOYMENT_GUIDE_ZH.md"):
        text = (ROOT / name).read_text()
        assert "conda activate co-scientist" in text
        assert "source .venv/bin/activate" in text


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
