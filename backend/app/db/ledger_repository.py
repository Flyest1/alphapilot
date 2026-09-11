"""Append-only ledger RPC boundary, separate from the asset repository.

Statement bytes are never sent to Supabase. Publication and capture are separate
transactions so failed publication can be retried without losing provenance.
"""

import csv
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from io import StringIO
import json

from pydantic import AwareDatetime, TypeAdapter

from app.models.account_ledger import Identifier, LedgerEvent
from app.services.ledger.reconciliation import reconcile_ledger
from app.services.ledger.replay import replay_ledger
from app.services.ledger.statement import normalize_statement


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def digest(value):
    return sha256(canonical(value).encode("utf-8")).hexdigest()


class LedgerRepository:
    def __init__(self, client):
        self.client = client

    def _rpc(self, name, **params):
        return (
            self.client.rpc(name, {f"p_{key}": value for key, value in params.items()})
            .execute()
            .data
        )

    def import_statement(
        self, batch, *, raw: bytes, mapping: dict, account_id: str, observed_at: str
    ):
        account_id = TypeAdapter(Identifier).validate_python(account_id)
        timestamp = TypeAdapter(AwareDatetime).validate_python(observed_at)
        expected_batch = normalize_statement(
            raw, account_id=account_id, observed_at=observed_at, mapping=mapping
        )
        if batch != expected_batch:
            raise ValueError("Normalized statement does not match original bytes and mapping")
        document_hash = sha256(raw).hexdigest()
        if batch["document_hash"] != document_hash or batch["coverage_verified"] is not False:
            raise ValueError("Invalid document provenance")
        reader = csv.DictReader(StringIO(raw.decode("utf-8-sig"), newline=""))
        raw_rows = list(reader)
        if len(raw_rows) != len(batch["sources"]):
            raise ValueError("Source row count mismatch")
        sources = []
        for number, (source, row) in enumerate(zip(batch["sources"], raw_rows), start=1):
            expected = {
                "source_key": f"{document_hash}:{number}",
                "payload_hash": digest(row),
                "document_hash": document_hash,
                "row_number": number,
            }
            if any(source.get(key) != value for key, value in expected.items()):
                raise ValueError("Invalid row provenance")
            sources.append(expected)
        source_ids = {(source["source_key"], source["payload_hash"]) for source in sources}
        events = []
        for row in batch["events"]:
            event = LedgerEvent.model_validate(row)
            if (
                event.account_id != account_id
                or event.source_type != "statement"
                or event.observed_at != timestamp
                or (event.source_key, event.source_record_hash) not in source_ids
            ):
                raise ValueError("Event evidence does not belong to this import")
            events.append(event.model_dump(mode="json"))
        errors = []
        for error in batch["errors"]:
            if (
                type(error.get("row")) is not int
                or not 1 <= error["row"] <= len(sources)
                or error.get("reason") != "invalid_event"
                or not isinstance(error.get("fields"), list)
                or any(field not in LedgerEvent.model_fields for field in error["fields"])
            ):
                raise ValueError("Invalid safe error metadata")
            errors.append({key: error[key] for key in ("row", "fields", "reason")})
        if len(events) + len(errors) != len(sources):
            raise ValueError("Every source row requires an outcome")
        result = {
            "errors": errors,
            "status": "partial" if errors and events else "validated" if events else "rejected",
            "coverage_verified": False,
        }
        manifest = {
            "document_hash": document_hash,
            "mapping_hash": batch["mapping_hash"],
            "schema_version": batch["schema_version"],
            "observed_at": timestamp.isoformat(),
            "source_type": "statement",
            "source_count": len(sources),
            "coverage_verified": False,
        }
        run_key = digest(
            {"manifest": manifest, "account_id": account_id, "events": events, "result": result}
        )
        self._rpc(
            "ledger_capture_import",
            account_id=account_id,
            run_key=run_key,
            manifest=manifest,
            sources=sources,
        )
        return self._rpc(
            "ledger_publish_import",
            account_id=account_id,
            run_key=run_key,
            events=events,
            result=result,
        )

    def _read_account(self, account_id):
        """One database snapshot includes all revisions and incomplete imports."""
        TypeAdapter(Identifier).validate_python(account_id)
        snapshot = self._rpc("ledger_read_account", account_id=account_id)
        events = []
        for item in snapshot["events"]:
            event = LedgerEvent.model_validate(item)
            if event.account_id != account_id:
                raise ValueError("Cross-account event returned")
            events.append(event.model_dump(mode="json"))
        return events, snapshot["imports"]

    def list_events(self, account_id):
        return self._read_account(account_id)[0]

    def save_reconciliation(self, opening, *, as_of: str, known_at: datetime, observed=None):
        account_id = opening["account_id"]
        events, imports = self._read_account(account_id)
        replay = replay_ledger(opening, events, as_of=as_of, known_at=known_at)
        relevant_imports = []
        for item in imports:
            if (
                TypeAdapter(AwareDatetime).validate_python(item["manifest"]["observed_at"])
                > known_at
            ):
                continue
            relevant_imports.append(item)
            publication = item["result"]
            if publication is None or publication["status"] != "validated":
                replay["issues"].append(
                    {"reason": "incomplete_statement_import", "run_key": item["run_key"]}
                )
        if replay["issues"]:
            replay["status"] = "incomplete"
        result = {
            "replay": replay,
            "reconciliation": reconcile_ledger(replay, observed) if observed is not None else None,
        }
        # Only Decimal values from the engine need conversion. Invalid evidence is
        # validated above, so arbitrary objects cannot enter this serializer.
        result = json.loads(
            json.dumps(
                result,
                default=lambda value: (
                    format(value, "f") if isinstance(value, Decimal) else str(value)
                ),
                allow_nan=False,
            )
        )
        inputs = {
            "opening": opening,
            "observed": observed,
            "as_of": as_of,
            "known_at": known_at.isoformat(),
            "events_hash": digest(events),
            "imports_hash": digest(relevant_imports),
        }
        run_key = digest({"input": inputs, "result": result})
        return self._rpc(
            "ledger_save_reconciliation",
            account_id=account_id,
            run_key=run_key,
            input=inputs,
            result=result,
        )
