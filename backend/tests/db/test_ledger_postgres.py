"""Opt-in real PostgreSQL contract checks; run only on a disposable local database.

Set LEDGER_TEST_PSQL to psql after applying migration 026 with Supabase-compatible
roles. The test endpoint is fixed to loopback:55439, user ledger_test, database postgres.
No hosting environment variables or operating credentials are read.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.db.ledger_repository import LedgerRepository
from app.services.ledger.statement import normalize_statement

PSQL = os.environ.get("LEDGER_TEST_PSQL")
pytestmark = pytest.mark.skipif(not PSQL, reason="Disposable local PostgreSQL not configured")


def sql(query):
    result = subprocess.run(
        [
            PSQL,
            "-X",
            "-qAt",
            "-h",
            "127.0.0.1",
            "-p",
            "55439",
            "-U",
            "ledger_test",
            "-d",
            "postgres",
            "-v",
            "ON_ERROR_STOP=1",
        ],
        input=query,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()


def literal(value):
    if isinstance(value, (dict, list)):
        return "'" + json.dumps(value).replace("'", "''") + "'::jsonb"
    return "'" + value.replace("'", "''") + "'::text"


class RpcClient:
    def rpc(self, name, params):
        assert name.startswith("ledger_") and name.replace("_", "").isalpha()
        args = ",".join(f"{key} => {literal(value)}" for key, value in params.items())
        return SimpleNamespace(
            execute=lambda: SimpleNamespace(
                data=json.loads(sql(f"SET ROLE service_role; SELECT public.{name}({args});"))
            )
        )


def fixture(account, observed_at="2026-09-11T12:00:00+09:00"):
    raw = b"date,gross,fee,tax,net\n2026-09-01,10.000000000001,0.000000000001,0,10\n"
    mapping = {
        "version": "statement_csv_v1",
        "columns": {
            "event_date": "date",
            "gross_amount": "gross",
            "fee": "fee",
            "tax": "tax",
            "net_cash_amount": "net",
        },
        "constants": {
            "event_type": "deposit",
            "currency": "USD",
            "timezone": "Asia/Seoul",
            "precision": "date_only",
            "quality": "verified",
        },
    }
    batch = normalize_statement(raw, account_id=account, observed_at=observed_at, mapping=mapping)
    return raw, batch, mapping


def opening(account):
    return {
        "account_id": account,
        "as_of": "2026-08-31",
        "source_record_hash": "a" * 64,
        "cash_basis": "settled",
        "cash": {"KRW": "0", "USD": "0"},
        "receivables": {"KRW": "0", "USD": "0"},
        "payables": {"KRW": "0", "USD": "0"},
        "positions": {},
    }


def test_real_concurrent_import_and_reconciliation():
    account = "pg-test-" + uuid4().hex
    repo = LedgerRepository(RpcClient())
    raw, batch, mapping = fixture(account)

    def import_one(_):
        return repo.import_statement(
            batch,
            raw=raw,
            mapping=mapping,
            account_id=account,
            observed_at="2026-09-11T12:00:00+09:00",
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(import_one, range(8)))
    assert all(item == results[0] for item in results)
    assert len(repo.list_events(account)) == 1
    result = repo.save_reconciliation(
        opening(account),
        as_of="2026-09-11",
        known_at=datetime.fromisoformat("2026-09-11T12:00:00+09:00"),
    )
    stored = json.loads(
        sql(
            "SELECT result FROM ledger_reconciliation_runs "
            f"WHERE account_id={literal(account)} "
            f"AND run_key={literal(result['run_key'])};"
        )
    )
    assert stored["replay"]["balances"]["cash"]["USD"] == "10.000000000000"
    assert stored["replay"]["status"] == "replayed"
    assert sql(f"SELECT count(*) FROM ledger_postings WHERE account_id={literal(account)};") == "4"


def test_rejected_and_pending_imports_survive_restart_and_mark_replay_incomplete():
    account = "pg-test-" + uuid4().hex
    raw, batch, mapping = fixture(account)
    repo = LedgerRepository(RpcClient())
    repo.import_statement(
        batch, raw=raw, mapping=mapping, account_id=account, observed_at="2026-09-11T12:00:00+09:00"
    )
    # A separate captured import has no publication, as after process failure.
    repo._rpc(
        "ledger_capture_import",
        account_id=account,
        run_key="e" * 64,
        manifest={
            "document_hash": "a" * 64,
            "mapping_hash": "b" * 64,
            "schema_version": "statement_csv_v1",
            "source_type": "statement",
            "source_count": 0,
            "observed_at": "2026-09-11T12:00:00+09:00",
            "coverage_verified": False,
        },
        sources=[],
    )
    restarted = LedgerRepository(RpcClient())
    result = restarted.save_reconciliation(
        opening(account),
        as_of="2026-09-11",
        known_at=datetime.fromisoformat("2026-09-11T12:00:00+09:00"),
    )
    stored = json.loads(
        sql(
            "SELECT result FROM ledger_reconciliation_runs "
            f"WHERE account_id={literal(account)} "
            f"AND run_key={literal(result['run_key'])};"
        )
    )
    assert stored["replay"]["status"] == "incomplete"
    assert "incomplete_statement_import" in {
        issue["reason"] for issue in stored["replay"]["issues"]
    }


def test_sql_constraints_and_privileges():
    checks = Path(__file__).with_name("ledger_storage_checks.sql").read_text(encoding="utf-8")
    sql(checks)


def test_later_observation_deduplicates_without_rewriting_first_observation():
    account = "pg-test-" + uuid4().hex
    repo = LedgerRepository(RpcClient())
    raw, batch, mapping = fixture(account)
    repo.import_statement(
        batch, raw=raw, mapping=mapping, account_id=account, observed_at="2026-09-11T12:00:00+09:00"
    )
    raw, later, mapping = fixture(account, observed_at="2026-09-11T13:00:00+09:00")
    repo.import_statement(
        later, raw=raw, mapping=mapping, account_id=account, observed_at="2026-09-11T13:00:00+09:00"
    )
    events, imports = repo._read_account(account)
    assert len(events) == 1 and len(imports) == 2
    assert events[0]["observed_at"] == "2026-09-11T12:00:00+09:00"
    assert all(item["result"]["status"] == "validated" for item in imports)
