"""Replay local JSON/CSV evidence into a new output file. No DB or network access."""

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.ledger.io import read_events_csv  # noqa: E402
from app.services.ledger.reconciliation import reconcile_ledger  # noqa: E402
from app.services.ledger.replay import replay_ledger  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--events-csv", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    payload = json.loads(raw)
    rows = payload.get("events", [])
    hashes = {"input": hashlib.sha256(raw).hexdigest()}
    if args.events_csv:
        if rows:
            raise ValueError("Choose JSON events or CSV events, not both")
        csv_bytes = args.events_csv.read_bytes()
        rows = read_events_csv(csv_bytes.decode("utf-8-sig"))
        hashes["events_csv"] = hashlib.sha256(csv_bytes).hexdigest()
    result = replay_ledger(
        payload["opening"],
        rows,
        as_of=payload["as_of"],
        known_at=datetime.fromisoformat(payload["known_at"].replace("Z", "+00:00")),
    )
    if "observed" in payload:
        result["reconciliation"] = reconcile_ledger(result, payload["observed"])
    result["input_hashes"] = hashes
    result["synthetic"] = payload.get("synthetic", False)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, default=str, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
