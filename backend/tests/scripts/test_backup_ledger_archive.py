import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def cli(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[3] / "scripts/backup_ledger_archive.py"
    spec = importlib.util.spec_from_file_location("ledger_backup_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return module


def test_cli_roundtrip_and_redacted_errors(cli, tmp_path, capsys):
    source = tmp_path / "backups/ledger_statements"
    raw = b"PRIVATE_ACCOUNT,PRIVATE_BALANCE\r\n"
    folder = source / hashlib.sha256(raw).hexdigest()
    folder.mkdir(parents=True)
    (folder / "original.csv").write_bytes(raw)
    mapping = b'{"private":"PRIVATE_MAPPING"}'
    (folder / f"mapping-{hashlib.sha256(mapping).hexdigest()}.json").write_bytes(mapping)
    output = tmp_path / "backups/copy.zip"
    destination = tmp_path / "backups/restored"
    assert cli.main(["backup", str(source), "--output", str(output)]) == 0
    assert cli.main(["verify", str(output)]) == 0
    assert cli.main(["restore", str(output), "--destination", str(destination)]) == 0
    assert cli.main(["restore", str(output), "--destination", str(destination)]) == 1
    captured = capsys.readouterr()
    for line in captured.out.splitlines():
        assert json.loads(line)["files"] == 2
    assert "PRIVATE" not in captured.out + captured.err
    assert str(tmp_path) not in captured.out + captured.err
    assert json.loads(captured.err)["reason"] == "ledger_archive_failed"
