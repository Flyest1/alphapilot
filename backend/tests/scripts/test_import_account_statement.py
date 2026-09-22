import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def cli(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "statement_cli", ROOT / "scripts/import_account_statement.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return module


def inputs(tmp_path):
    raw = b"date,amount,secret\n2026-09-10,1.2300,PRIVATE\n"
    source = tmp_path / "source.csv"
    source.write_bytes(raw)
    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps(
            {
                "version": "statement_csv_v1",
                "columns": {"event_date": "date", "net_cash_amount": "amount"},
                "constants": {
                    "event_type": "deposit",
                    "currency": "USD",
                    "timezone": "Asia/Seoul",
                    "precision": "date_only",
                },
            }
        )
    )
    return source, [
        str(source),
        "--mapping",
        str(mapping),
        "--account-id",
        "private-account",
        "--observed-at",
        "2026-09-11T12:00:00+09:00",
    ]


def test_local_import_archives_immutably_and_never_opens_database(
    cli, tmp_path, monkeypatch, capsys
):
    source, args = inputs(tmp_path)
    monkeypatch.setattr(cli, "_repository", lambda: pytest.fail("Unexpected database access"))
    assert cli.main(args) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["stored"] is False and receipt["events"] == 1
    assert "private-account" not in json.dumps(receipt)
    archive = (
        tmp_path / "backups/ledger_statements" / hashlib.sha256(source.read_bytes()).hexdigest()
    )
    assert (archive / "original.csv").read_bytes() == source.read_bytes()
    before = {p.name: p.read_bytes() for p in archive.iterdir()}
    assert cli.main(args) == 0
    assert {p.name: p.read_bytes() for p in archive.iterdir()} == before
    (archive / "original.csv").write_bytes(b"existing evidence")
    assert cli.main(args) == 1
    assert (archive / "original.csv").read_bytes() == b"existing evidence"


def test_invalid_evidence_archived_before_validation_without_error_leaks(cli, tmp_path, capsys):
    source, args = inputs(tmp_path)
    source.write_bytes(b"date,date\nPRIVATE,PRIVATE\n")
    assert cli.main(args) == 1
    output = capsys.readouterr()
    assert "PRIVATE" not in output.out + output.err
    originals = list((tmp_path / "backups").rglob("original.csv"))
    assert originals[0].read_bytes() == source.read_bytes()


def test_archive_outside_backups_rejected(cli, tmp_path):
    _, args = inputs(tmp_path)
    assert cli.main(args + ["--archive-dir", str(tmp_path / "public")]) == 1
    assert not (tmp_path / "public").exists()


def test_context_requires_persistence(cli, tmp_path):
    _, args = inputs(tmp_path)
    assert cli.main(args + ["--context", str(tmp_path / "context.json")]) == 1


def test_explicit_persist_passes_normalized_events_and_context(cli, tmp_path, monkeypatch, capsys):
    source, args = inputs(tmp_path)
    calls = []

    class Repository:
        def import_statement(self, batch, **kwargs):
            calls.append((batch, kwargs))
            return {"run_key": "a" * 64}

        def save_reconciliation(self, opening, **kwargs):
            calls.append((opening, kwargs))

    monkeypatch.setattr(cli, "_repository", Repository)
    context = tmp_path / "context.json"
    context.write_text(
        json.dumps(
            {
                "opening": {"account_id": "private-account"},
                "as_of": "2026-09-11",
                "known_at": "2026-09-11T12:00:00+09:00",
            }
        )
    )
    assert cli.main(args + ["--persist", "--context", str(context)]) == 0
    assert calls[0][1]["raw"] == source.read_bytes()
    assert calls[0][1]["mapping"] == json.loads((tmp_path / "mapping.json").read_text())
    assert calls[0][0]["events"][0]["fee"] is None
    assert len(calls) == 2
    assert json.loads(capsys.readouterr().out)["stored"] is True
