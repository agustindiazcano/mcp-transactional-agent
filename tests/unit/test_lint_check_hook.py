import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

HOOK = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "lint_check.py"


def _load_hook() -> ModuleType:
    spec = importlib.util.spec_from_file_location("lint_check_hook", HOOK)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lint_check = _load_hook()


def _make_python(venv: Path) -> Path:
    folder = venv / ("Scripts" if sys.platform == "win32" else "bin")
    folder.mkdir(parents=True)
    python = folder / ("python.exe" if sys.platform == "win32" else "python")
    python.touch()
    return python


def test_prefers_the_active_virtualenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    active = _make_python(tmp_path / "active")
    _make_python(tmp_path / "project" / ".venv")
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "active"))

    assert lint_check.project_python(str(tmp_path / "project")) == str(active)


def test_uses_the_project_venv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    python = _make_python(tmp_path / ".venv")

    assert lint_check.project_python(str(tmp_path)) == str(python)


def test_falls_back_to_the_running_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)

    assert lint_check.project_python(str(tmp_path)) == sys.executable


@pytest.mark.parametrize(
    "path, expected",
    [
        ("src/worker/worker.py", True),
        ("src\\core\\models.py", True),
        ("tests/unit/test_x.py", False),
        ("scripts/seed_orders.py", False),
    ],
)
def test_type_checks_only_src_like_ci(path: str, expected: bool, tmp_path: Path) -> None:
    assert lint_check.should_type_check(path, str(tmp_path)) is expected
