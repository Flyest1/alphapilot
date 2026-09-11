"""Compare immutable local price evidence; never connect to or rewrite the operating DB."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.measurement_audit import audit_recommendations  # noqa: E402
from app.services.price_revision_audit import compare_price_evidence  # noqa: E402


def read_evidence(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def frames(histories: dict) -> dict:
    result = {}
    for ticker, rows in histories.items():
        if rows:
            frame = pd.DataFrame(rows).set_index("date")
            frame.index = pd.to_datetime(frame.index)
            result[ticker] = frame
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--calendar-manifest", type=Path, required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    payload, source_hash = read_evidence(args.input)
    manifest, calendar_hash = read_evidence(args.calendar_manifest)
    calendar_by_ticker, fresh, comparisons, hashes = {}, {}, {}, {}
    for ticker, rows in payload["histories"].items():
        # This historical export records KR as pykrx and US/US-listed ETFs as yfinance.
        provider = payload.get("price_provenance", {}).get(ticker, {}).get("provider")
        market = {"pykrx": "KR", "yfinance": "US"}.get(provider)
        if market:
            calendar_by_ticker[ticker] = manifest["calendars"][market]
        # No unchecked ticker interpolation into filesystem paths.
        if not ticker or any(
            char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-^" for char in ticker
        ):
            raise ValueError("Unsupported ticker path")
        path = args.evidence_dir / f"{ticker}.json"
        if not path.exists():
            comparisons[ticker] = {"status": "missing_refreshed_evidence"}
            continue
        evidence, hashes[ticker] = read_evidence(path)
        if evidence.get("ticker") != ticker or evidence.get("provider") != provider:
            raise ValueError("Evidence identity mismatch")
        if evidence.get("status") != "ok":
            comparisons[ticker] = {"status": "unavailable_refreshed_evidence"}
            continue
        fresh[ticker] = [
            {
                "date": row["date"],
                **{key: row.get(key.title()) for key in ("open", "high", "low", "close")},
                **({"dividend": row["Dividends"]} if "Dividends" in row else {}),
                **({"split": row["Stock Splits"]} if "Stock Splits" in row else {}),
            }
            for row in evidence["rows"]
        ]
        comparisons[ticker] = compare_price_evidence(
            rows, fresh[ticker], start=evidence["start"], end=args.as_of
        )
        comparisons[ticker]["provider_request"] = {
            key: value for key, value in evidence.items() if key != "rows"
        }
    cycles = payload["cycles"]
    archived_frames = frames(payload["histories"])
    results = {
        "archived_unchecked": audit_recommendations(cycles, archived_frames, as_of=args.as_of),
        "archived_calendar": audit_recommendations(
            cycles, archived_frames, as_of=args.as_of, session_calendars=calendar_by_ticker
        ),
        "refreshed_calendar": audit_recommendations(
            cycles, frames(fresh), as_of=args.as_of, session_calendars=calendar_by_ticker
        ),
        "price_comparisons": comparisons,
        "lineage": {
            "input_sha256": source_hash,
            "calendar_sha256": calendar_hash,
            "evidence_sha256_by_ticker": hashes,
            "calendar_manifest": manifest,
            "research_only": True,
            "promotion_permitted": False,
            "original_price_basis_verified": False,
            "note": "Refreshed prices are sensitivity analysis, not certified corrected outcomes.",
        },
    }
    # Refuse reuse, including the input/evidence directory; never overwrite prior artifacts.
    args.output_dir.mkdir()
    for name, result in results.items():
        with (args.output_dir / f"{name}.json").open("x", encoding="utf-8") as output:
            json.dump(result, output, ensure_ascii=False, allow_nan=False, indent=2)
            output.write("\n")
    print(
        json.dumps(
            {
                name: result["evaluated_count"]
                for name, result in results.items()
                if "evaluated_count" in result
            }
        )
    )


if __name__ == "__main__":
    main()
