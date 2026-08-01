from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
import subprocess
import zipfile

import pytest


UPDATER_PATH = Path(__file__).parents[1] / "deploy" / "skyportal-home-update"
LOADER = SourceFileLoader("skyportal_home_updater", str(UPDATER_PATH))
SPEC = spec_from_loader(LOADER.name, LOADER)
updater = module_from_spec(SPEC)
LOADER.exec_module(updater)


def result(returncode=0, stdout=""):
    return subprocess.CompletedProcess(["git"], returncode, stdout=stdout)


def test_forward_update_requires_installed_commit_in_history(monkeypatch):
    monkeypatch.setattr(updater, "git", lambda *args, **kwargs: result(1))

    with pytest.raises(updater.UpdateSkipped, match="not in the GitHub history"):
        updater.verify_forward_update(Path("/repo"), "installed", "remote")


def test_forward_update_rejects_diverged_remote(monkeypatch):
    responses = iter((result(), result(1)))
    monkeypatch.setattr(updater, "git", lambda *args, **kwargs: next(responses))

    with pytest.raises(updater.UpdateSkipped, match="does not descend"):
        updater.verify_forward_update(Path("/repo"), "installed", "remote")


def test_forward_update_accepts_descendant(monkeypatch):
    responses = iter((result(), result()))
    monkeypatch.setattr(updater, "git", lambda *args, **kwargs: next(responses))

    updater.verify_forward_update(Path("/repo"), "installed", "remote")


def test_extract_revision_rejects_archive_path_traversal(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    destination = tmp_path / "candidate"
    monkeypatch.setattr(updater, "STATE_DIR", state)

    def fake_git(*arguments, **kwargs):
        output_argument = next(item for item in arguments if item.startswith("--output="))
        archive_path = Path(output_argument.partition("=")[2])
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("../outside", "unsafe")
        return result()

    monkeypatch.setattr(updater, "git", fake_git)

    with pytest.raises(RuntimeError, match="unsafe path"):
        updater.extract_revision(tmp_path / "repo", "revision", destination)
    assert not (tmp_path / "outside").exists()


def test_failed_health_check_restores_previous_release(tmp_path, monkeypatch):
    app = tmp_path / "app"
    previous = tmp_path / "app.previous"
    candidate = tmp_path / "candidate"
    app.mkdir()
    candidate.mkdir()
    (app / "release").write_text("old", encoding="utf-8")
    (candidate / "release").write_text("new", encoding="utf-8")
    health = iter((False, True))

    monkeypatch.setattr(updater, "APP_DIR", app)
    monkeypatch.setattr(updater, "PREVIOUS_DIR", previous)
    monkeypatch.setattr(updater, "service_health", lambda timeout=40: next(health))
    monkeypatch.setattr(
        updater,
        "run",
        lambda *args, **kwargs: result(stdout="service status"),
    )

    with pytest.raises(RuntimeError, match="failed its health check"):
        updater.activate(candidate, "1234567890abcdef")

    assert (app / "release").read_text(encoding="utf-8") == "old"
    assert not previous.exists()


def test_activation_failure_before_switch_does_not_move_candidate(tmp_path, monkeypatch):
    app = tmp_path / "missing-app"
    previous = tmp_path / "app.previous"
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    commands = []

    monkeypatch.setattr(updater, "APP_DIR", app)
    monkeypatch.setattr(updater, "PREVIOUS_DIR", previous)
    monkeypatch.setattr(
        updater,
        "run",
        lambda command, **kwargs: commands.append(command) or result(),
    )

    with pytest.raises(FileNotFoundError):
        updater.activate(candidate, "1234567890abcdef")

    assert candidate.exists()
    assert not previous.exists()
    assert ["systemctl", "start", updater.SERVICE] in commands
