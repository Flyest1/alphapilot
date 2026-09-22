"""Inspect ledger issues or append an explicit review; no original records are changed."""

import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from pydantic import AwareDatetime, TypeAdapter  # noqa: E402


def _repository():
    from dotenv import load_dotenv
    from supabase import create_client
    from app.db.ledger_repository import LedgerRepository

    load_dotenv(ROOT / "backend/.env", override=False)
    return LedgerRepository(
        create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--account-id", required=True)
    inspect.add_argument("--opening-date", required=True)
    inspect.add_argument("--as-of", required=True)
    inspect.add_argument("--known-at", required=True)
    inspect.add_argument("--output", type=Path, required=True)
    record = commands.add_parser("record")
    record.add_argument("--account-id", required=True)
    record.add_argument("--request", type=Path, required=True)
    record.add_argument("--expected-revision", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            output = args.output.resolve()
            output.relative_to((ROOT / "backups").resolve())
            if output.exists():
                raise ValueError("Output already exists")
            date.fromisoformat(args.opening_date)
            date.fromisoformat(args.as_of)
            result = _repository().inspect_reviews(
                args.account_id,
                opening_date=args.opening_date,
                as_of=args.as_of,
                known_at=TypeAdapter(AwareDatetime).validate_python(args.known_at),
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False, allow_nan=False, indent=2)
            receipt = {
                "issues": len(result["issues"]),
                "duplicate_candidates": len(result["duplicate_candidates"]),
                "coverage_verified": False,
            }
        else:
            with args.request.open("rb") as stream:
                raw = stream.read(16385)
            if len(raw) > 16384 or args.expected_revision < 0:
                raise ValueError("Invalid review request")
            result = _repository().record_review(
                args.account_id, json.loads(raw), expected_revision=args.expected_revision
            )
            receipt = {key: result[key] for key in ("review_key", "revision", "reviewed_at")}
        print(json.dumps(receipt))
        return 0
    except Exception:
        print(json.dumps({"status": "failed", "reason": "ledger_review_failed"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
