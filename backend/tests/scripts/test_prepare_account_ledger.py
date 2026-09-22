import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def cli(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "prepare_cli", ROOT / "scripts/prepare_account_ledger.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return module


def test_init_and_missing_material_report_work_offline_without_overwriting(cli, tmp_path):
    packet = tmp_path / "backups/preparation"
    assert cli.main(["init", "--output-dir", str(packet)]) == 0
    manifest = packet / "manifest.json"
    assert json.loads(manifest.read_text())["account_id"] is None
    assert json.loads((packet / "opening.json").read_text())["cash"]["KRW"] is None
    before = manifest.read_bytes()
    assert cli.main(["init", "--output-dir", str(packet)]) == 1
    output = tmp_path / "backups/result"
    assert cli.main(["check", str(manifest), "--output-dir", str(output)]) == 2
    result = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert result["status"] == "blocked"
    assert "자료 준비" in (output / "report.md").read_text(encoding="utf-8")
    saved = (output / "report.json").read_bytes()
    assert cli.main(["check", str(manifest), "--output-dir", str(output)]) == 1
    assert saved == (output / "report.json").read_bytes()
    assert before == manifest.read_bytes()


def test_output_cannot_escape_private_backups(cli, tmp_path):
    outside = tmp_path / "public-output"
    assert cli.main(["init", "--output-dir", str(outside)]) == 1
    assert not outside.exists()


def test_failure_does_not_echo_input_or_exception_details(cli, tmp_path, capsys):
    path = tmp_path / "PRIVATE_SECRET.json"
    path.write_text('{"secret":"PRIVATE_SECRET"}')
    output = tmp_path / "backups/result"
    assert cli.main(["check", str(path), "--output-dir", str(output)]) == 2
    assert "PRIVATE_SECRET" not in capsys.readouterr().out
    assert "PRIVATE_SECRET" not in (output / "report.json").read_text()


def test_cli_has_no_persistence_mode_and_runs_without_network(cli, tmp_path, monkeypatch):
    import socket

    monkeypatch.setattr(socket, "socket", lambda *a, **k: pytest.fail("Unexpected network access"))
    packet = tmp_path / "backups/materials"
    assert cli.main(["init", "--output-dir", str(packet)]) == 0
    args = ["check", str(packet / "manifest.json"), "--output-dir", str(tmp_path / "backups/check")]
    assert cli.main(args) == 2
    with pytest.raises(SystemExit) as exc:
        cli.main(args + ["--persist"])
    assert exc.value.code == 2
