"""Archive and normalize explicitly mapped CSV evidence; DB persistence is opt-in.

Retrying identical observations is idempotent; later observations preserve the
first database observation, while earlier observations are rejected. This generic
adapter has only synthetic fixtures and does not claim actual Toss CSV support.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from pydantic import AwareDatetime, TypeAdapter  # noqa: E402

from app.models.account_ledger import Identifier  # noqa: E402
from app.services.ledger.statement import MAX_DOCUMENT_BYTES, normalize_statement  # noqa: E402


def _repository():
    # Import and read credentials only after explicit --persist.
    from dotenv import load_dotenv
    from supabase import create_client

    from app.db.ledger_repository import LedgerRepository

    load_dotenv(ROOT / "backend/.env", override=False)
    return LedgerRepository(
        create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    )


def _bounded_read(path):
    with path.open("rb") as stream:
        raw = stream.read(MAX_DOCUMENT_BYTES + 1)
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ValueError("Input exceeds size limit")
    return raw


def _archive(path, raw):
    # Re-resolve the actual file to reject symlink escapes as well as '..'.
    path.resolve().relative_to((ROOT / "backups").resolve())
    try:
        with path.open("xb") as stream:
            stream.write(raw)
    except FileExistsError:
        with path.open("rb") as stream:
            if stream.read(len(raw) + 1) != raw:
                raise ValueError("Archived evidence conflict") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--persist", action="store_true")
    parser.add_argument("--context", type=Path)
    parser.add_argument("--archive-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.context and not args.persist:
            raise ValueError("Context requires persistence")
        archive_dir = (args.archive_dir or ROOT / "backups/ledger_statements").resolve()
        archive_dir.relative_to((ROOT / "backups").resolve())
        raw = _bounded_read(args.input)
        document_hash = hashlib.sha256(raw).hexdigest()
        folder = archive_dir / document_hash
        folder.resolve().relative_to((ROOT / "backups").resolve())
        folder.mkdir(parents=True, exist_ok=True)
        _archive(folder / "original.csv", raw)
        mapping_raw = _bounded_read(args.mapping)
        mapping_digest = hashlib.sha256(mapping_raw).hexdigest()
        _archive(folder / f"mapping-{mapping_digest}.json", mapping_raw)
        TypeAdapter(Identifier).validate_python(args.account_id)
        TypeAdapter(AwareDatetime).validate_python(args.observed_at)
        mapping = json.loads(mapping_raw)
        batch = normalize_statement(
            raw,
            account_id=args.account_id,
            observed_at=args.observed_at,
            mapping=mapping,
        )
        normalized = json.dumps(
            batch, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        normalized_digest = hashlib.sha256(normalized).hexdigest()
        context_digest = hashlib.sha256(
            json.dumps(
                [args.account_id, args.observed_at], ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        _archive(
            folder
            / f"normalized-{batch['mapping_hash']}-{context_digest}-{normalized_digest}.json",
            normalized,
        )
        context = None
        if args.context:
            context_raw = _bounded_read(args.context)
            _archive(
                folder / f"context-{hashlib.sha256(context_raw).hexdigest()}.json", context_raw
            )
            context = json.loads(context_raw)
            if (
                not isinstance(context, dict)
                or set(context) - {"opening", "as_of", "known_at", "observed"}
                or context["opening"]["account_id"] != args.account_id
            ):
                raise ValueError("Invalid reconciliation context")
            context["known_at"] = TypeAdapter(AwareDatetime).validate_python(context["known_at"])
        events, errors = len(batch["events"]), len(batch["errors"])
        receipt = {
            "document_hash": document_hash,
            "status": "partial" if errors and events else "validated" if events else "rejected",
            "events": events,
            "errors": errors,
            "stored": False,
        }
        if args.persist:
            repository = _repository()
            stored = repository.import_statement(
                batch,
                raw=raw,
                mapping=mapping,
                account_id=args.account_id,
                observed_at=args.observed_at,
            )
            receipt["stored"] = True
            if isinstance(stored, dict) and isinstance(stored.get("run_key"), str):
                key = stored["run_key"]
                if len(key) == 64 and all(character in "0123456789abcdef" for character in key):
                    receipt["run_key"] = key
            if context:
                repository.save_reconciliation(
                    context["opening"],
                    as_of=context["as_of"],
                    known_at=context["known_at"],
                    observed=context.get("observed"),
                )
        print(json.dumps(receipt))
        return 1 if errors or not events else 0
    except Exception:
        print(
            json.dumps({"status": "failed", "reason": "statement_import_failed"}), file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
