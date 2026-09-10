"""Audit a local JSON export without connecting to or changing a database."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.measurement_audit import audit_recommendations  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON with cycles and histories by ticker")
    parser.add_argument("--as-of", required=True, help="Last observable date, YYYY-MM-DD")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    source = args.input.read_bytes()
    payload = json.loads(source)
    histories = {}
    for ticker, rows in payload.get("histories", {}).items():
        if rows:
            frame = pd.DataFrame(rows).set_index("date")
            frame.index = pd.to_datetime(frame.index, utc=True)
            histories[ticker] = frame
    result = audit_recommendations(payload["cycles"], histories, as_of=args.as_of)
    result["input_sha256"] = hashlib.sha256(source).hexdigest()
    result["price_provenance"] = payload.get("price_provenance", {})
    # Exclusive creation protects both the input and any previous audit artifact.
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, allow_nan=False, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
