import importlib.util
import json
from pathlib import Path


def module(tmp_path):
    path = Path(__file__).resolve().parents[3] / "scripts/review_account_ledger.py"
    spec = importlib.util.spec_from_file_location("ledger_review_cli", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    result.ROOT = tmp_path
    return result


def test_inspect_refuses_public_output_before_database(tmp_path, monkeypatch):
    cli = module(tmp_path)
    monkeypatch.setattr(cli, "_repository", lambda: (_ for _ in ()).throw(AssertionError()))
    assert (
        cli.main(
            [
                "inspect",
                "--account-id",
                "demo",
                "--opening-date",
                "2026-09-01",
                "--as-of",
                "2026-09-22",
                "--known-at",
                "2026-09-23T00:00:00Z",
                "--output",
                str(tmp_path / "public.json"),
            ]
        )
        == 1
    )


def test_record_passes_explicit_review_and_expected_revision_without_echo(
    tmp_path, monkeypatch, capsys
):
    cli = module(tmp_path)
    calls = []

    class Repository:
        def record_review(self, account, request, **kwargs):
            calls.append((account, request, kwargs))
            return {
                "review_key": "a" * 64,
                "revision": 2,
                "reviewed_at": "2026-09-23T00:00:00Z",
                "account_id": account,
            }

    monkeypatch.setattr(cli, "_repository", Repository)
    path = tmp_path / "request.json"
    path.write_text(json.dumps({"kind": "import_resolution", "decision": "reopen"}))
    assert (
        cli.main(
            [
                "record",
                "--account-id",
                "PRIVATE",
                "--request",
                str(path),
                "--expected-revision",
                "1",
            ]
        )
        == 0
    )
    assert calls[0][2] == {"expected_revision": 1}
    assert "PRIVATE" not in capsys.readouterr().out
