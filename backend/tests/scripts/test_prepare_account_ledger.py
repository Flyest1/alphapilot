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


def test_incomplete_material_never_opens_operating_connection(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_operating_snapshot", lambda *a: pytest.fail("Unexpected DB read"))
    folder = tmp_path / "backups/material"
    assert cli.main(["init", "--output-dir", str(folder)]) == 0
    output = tmp_path / "backups/preview"
    assert (
        cli.main(
            [
                "preview",
                str(folder / "manifest.json"),
                "--read-operating",
                "--expected-project-id",
                "expected",
                "--output-dir",
                str(output),
            ]
        )
        == 2
    )
    result = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert result["storage_preview"]["status"] == "not_checked"
    assert not (output / "snapshot.json").exists()


def test_offline_preview_preserves_snapshot_and_never_loads_credentials(cli, tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "packet_fixture", ROOT / "backend/tests/services/test_ledger_preparation.py"
    )
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    fixtures.packet(tmp_path)
    snapshot = {
        "account_id": "local-example",
        "snapshot": {"events": [], "imports": [], "reviews": []},
    }
    path = tmp_path / "snapshot.json"
    fixtures.write_json(path, snapshot)
    monkeypatch.setattr(
        cli, "_operating_snapshot", lambda *a: pytest.fail("Unexpected credentials")
    )
    output = tmp_path / "backups/preview"
    args = [
        "preview",
        str(tmp_path / "manifest.json"),
        "--snapshot",
        str(path),
        "--output-dir",
        str(output),
    ]
    assert cli.main(args) == 0
    result = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert result["storage_preview"]["snapshot_source"] == "offline_snapshot"
    assert json.loads((output / "snapshot.json").read_text()) == snapshot
    assert "PRIVATE_MEMO" not in (output / "report.md").read_text(encoding="utf-8")
    assert cli.main(args) == 1


def test_failed_operating_read_is_blocked_without_empty_fallback(
    cli, tmp_path, monkeypatch, capsys
):
    evidence = {"account_id": "private-account"}
    monkeypatch.setattr(
        cli,
        "check_preparation",
        lambda *a, **k: (
            k["evidence"].update(evidence) or {"status": "ready_for_review", "blockers": []}
        ),
    )
    monkeypatch.setattr(cli, "render_preparation_report", lambda result: "safe report")

    def fail(*a):
        raise RuntimeError("PRIVATE_CREDENTIAL")

    monkeypatch.setattr(cli, "_operating_snapshot", fail)
    output = tmp_path / "backups/preview"
    assert (
        cli.main(
            [
                "preview",
                "unused",
                "--read-operating",
                "--expected-project-id",
                "expected",
                "--output-dir",
                str(output),
            ]
        )
        == 2
    )
    result = json.loads((output / "report.json").read_text())
    assert result["storage_preview"]["status"] == "failed"
    assert "PRIVATE_CREDENTIAL" not in capsys.readouterr().out
    assert not (output / "snapshot.json").exists()


def test_wrong_operating_project_is_rejected_before_client_creation(cli, monkeypatch):
    import supabase

    monkeypatch.setenv("SUPABASE_URL", "https://wrong.supabase.co")
    monkeypatch.setattr(supabase, "create_client", lambda *a: pytest.fail("Unexpected client"))
    with pytest.raises(ValueError):
        cli._operating_snapshot("account", "expected")


def test_existing_ledger_can_resolve_a_standalone_balance_difference(cli, tmp_path):
    spec = importlib.util.spec_from_file_location(
        "packet_fixture", ROOT / "backend/tests/services/test_ledger_preparation.py"
    )
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    fixtures.packet(tmp_path)
    closing_path = tmp_path / "closing.json"
    closing = json.loads(closing_path.read_text())
    closing["cash"]["USD"] = "16"
    fixtures.write_json(closing_path, closing)
    from app.services.ledger.statement import normalize_statement
    from app.services.ledger.storage_preview import proposed_import

    mapping = json.loads((tmp_path / "mapping.json").read_text())
    batch = normalize_statement(
        b"day,gross,fee,tax,net,memo\n2026-09-01,6,0,0,6,OLD\n",
        account_id="local-example",
        observed_at="2026-09-03T10:00:00+09:00",
        mapping=mapping,
    )
    snapshot = {
        "account_id": "local-example",
        "snapshot": {
            "events": batch["events"],
            "imports": [
                proposed_import(
                    batch, account_id="local-example", observed_at="2026-09-03T10:00:00+09:00"
                )
            ],
            "reviews": [],
        },
    }
    path = tmp_path / "snapshot.json"
    fixtures.write_json(path, snapshot)
    output = tmp_path / "backups/preview"
    assert (
        cli.main(
            [
                "preview",
                str(tmp_path / "manifest.json"),
                "--snapshot",
                str(path),
                "--output-dir",
                str(output),
            ]
        )
        == 0
    )
    result = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert result["local_status"] == "blocked"
    assert result["local_projection_blockers"] == [{"code": "balance_mismatch"}]
    assert result["storage_preview"]["reconciliation"]["balances_match"] is True
