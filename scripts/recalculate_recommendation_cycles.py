import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
load_dotenv(BACKEND / ".env")

from app.config import get_environment_settings, is_supabase_configured  # noqa: E402
from app.db.supabase_client import create_repository  # noqa: E402
from app.services.market_data_service import MarketDataService  # noqa: E402
from app.services.report.tracking import (  # noqa: E402
    MEASUREMENT_POLICY_VERSION,
    SHORT_LAYOUT_INVALID,
    SHORT_LAYOUT_LEGACY_SWAP,
    PerformanceTracker,
    classify_short_barrier_layout,
    measurement_metadata_updates,
    normalized_cycle_barrier_updates,
)

IMMUTABLE_CYCLE_FIELDS = {"id", "created_at", "updated_at"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview or apply recommendation-cycle measurement recalculation."
    )
    parser.add_argument("--apply", action="store_true", help="Write verified changes to Supabase.")
    parser.add_argument("--limit", type=int, default=1000, help="Maximum cycles to process.")
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=ROOT / "backups",
        help="Gitignored directory for backups and audit JSON.",
    )
    return parser.parse_args()


def collect_layout_audit(cycles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for cycle in cycles:
        layout = classify_short_barrier_layout(cycle)
        if layout not in {SHORT_LAYOUT_LEGACY_SWAP, SHORT_LAYOUT_INVALID}:
            continue
        normalization = normalized_cycle_barrier_updates(cycle)
        metadata = measurement_metadata_updates(cycle).get("metadata", cycle.get("metadata") or {})
        records.append(
            {
                "cycle_id": cycle.get("id"),
                "ticker": cycle.get("ticker"),
                "action": cycle.get("action"),
                "layout": layout,
                "reference_price": cycle.get("reference_price"),
                "target_price_before": cycle.get("target_price"),
                "stop_loss_before": cycle.get("stop_loss"),
                "target_price_expected": normalization.get(
                    "target_price", cycle.get("target_price")
                ),
                "stop_loss_expected": normalization.get("stop_loss", cycle.get("stop_loss")),
                "measurement_metadata_expected": metadata,
            }
        )
    return records


def verify_policy_records(
    records: list[dict[str, Any]], cycles: list[dict[str, Any]]
) -> list[dict[str, str]]:
    current_by_id = {str(cycle.get("id")): cycle for cycle in cycles}
    unresolved = []
    for record in records:
        cycle_id = str(record["cycle_id"])
        current = current_by_id.get(cycle_id)
        if current is None:
            unresolved.append({"cycle_id": cycle_id, "reason": "cycle_not_found"})
            continue
        expected_metadata = record["measurement_metadata_expected"]
        metadata = current.get("metadata") or {}
        metadata_matches = all(
            metadata.get(key) == value for key, value in expected_metadata.items()
        )
        if not metadata_matches:
            unresolved.append({"cycle_id": cycle_id, "reason": "measurement_metadata_missing"})
            continue
        if record["layout"] == SHORT_LAYOUT_LEGACY_SWAP and (
            current.get("target_price") != record["target_price_expected"]
            or current.get("stop_loss") != record["stop_loss_expected"]
        ):
            unresolved.append({"cycle_id": cycle_id, "reason": "barrier_normalization_missing"})
            continue
        if record["layout"] == SHORT_LAYOUT_INVALID and current.get("barrier_hit_at") is not None:
            unresolved.append({"cycle_id": cycle_id, "reason": "barrier_hit_not_cleared"})
    return unresolved


def restore_changed_cycles(
    repository: Any,
    original_cycles: list[dict[str, Any]],
    current_cycles: list[dict[str, Any]],
) -> dict[str, list[dict[str, str]] | list[str]]:
    original_by_id = {str(cycle.get("id")): cycle for cycle in original_cycles}
    current_by_id = {str(cycle.get("id")): cycle for cycle in current_cycles}
    restored = []
    failures = []
    for cycle_id, original in original_by_id.items():
        current = current_by_id.get(cycle_id)
        if current is None or _mutable_cycle_values(current) == _mutable_cycle_values(original):
            continue
        try:
            repository.update_recommendation_cycle(
                original["id"],
                _mutable_cycle_values(original),
            )
            restored.append(cycle_id)
        except Exception as exc:
            failures.append({"cycle_id": cycle_id, "reason": str(exc)})
    return {"restored_cycle_ids": restored, "failures": failures}


def _mutable_cycle_values(cycle: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in cycle.items() if key not in IMMUTABLE_CYCLE_FIELDS}


def _summary(
    cycles: list[dict[str, Any]],
    eligible: list[dict[str, Any]],
    records: list[dict[str, Any]],
    unresolved: list[dict[str, str]],
    failures: list[dict[str, str]],
    rollback: dict[str, Any] | None = None,
) -> None:
    swaps = sum(record["layout"] == SHORT_LAYOUT_LEGACY_SWAP for record in records)
    quarantined = sum(record["layout"] == SHORT_LAYOUT_INVALID for record in records)
    restored = len((rollback or {}).get("restored_cycle_ids", []))
    print(
        "Summary: "
        f"queried={len(cycles)} eligible={len(eligible)} swaps={swaps} "
        f"quarantined={quarantined} unresolved={len(unresolved)} "
        f"failures={len(failures)} restored={restored} "
        f"policy={MEASUREMENT_POLICY_VERSION}"
    )


def _write_audit(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    environment = get_environment_settings()
    if not is_supabase_configured(environment):
        print("Summary: configuration_unavailable=1")
        return 1

    repository = create_repository(environment)
    cycles = repository.list_recommendation_cycles(limit=max(1, args.limit))
    eligible = [cycle for cycle in cycles if cycle.get("status") != "superseded"]
    records = collect_layout_audit(eligible)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    args.backup_dir.mkdir(parents=True, exist_ok=True)
    audit_path = args.backup_dir / f"recommendation_cycles_recalculation_{timestamp}.json"
    base_audit = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "limit": max(1, args.limit),
        "queried_cycles": len(cycles),
        "eligible_cycles": len(eligible),
        "policy_version": MEASUREMENT_POLICY_VERSION,
        "layout_records": records,
    }

    if not args.apply:
        unresolved = verify_policy_records(records, cycles)
        _write_audit(
            audit_path,
            {
                **base_audit,
                "mode": "preview",
                "unresolved_malformed_rows": unresolved,
                "failures": [],
            },
        )
        _summary(cycles, eligible, records, unresolved, [])
        return 0

    backup_path = args.backup_dir / f"recommendation_cycles_{timestamp}.json"
    _write_audit(backup_path, {"cycles": cycles})
    backup_cycles = json.loads(backup_path.read_text(encoding="utf-8"))["cycles"]
    failures: list[dict[str, str]] = []
    unresolved: list[dict[str, str]] = []
    rollback: dict[str, Any] | None = None
    recalculated = 0
    try:
        tracker = PerformanceTracker(repository, MarketDataService(repository=repository))
        recalculated = tracker.recalculate_recommendation_cycles(limit=max(1, args.limit))
        updated_cycles = repository.list_recommendation_cycles(limit=max(1, args.limit))
        unresolved = verify_policy_records(records, updated_cycles)
        if unresolved:
            raise RuntimeError("post_write_verification_failed")
    except Exception as exc:
        failures.append({"reason": str(exc)})
        current_cycles = repository.list_recommendation_cycles(limit=max(1, args.limit))
        rollback = restore_changed_cycles(repository, backup_cycles, current_cycles)
        failures.extend(rollback["failures"])
        _write_audit(
            audit_path,
            {
                **base_audit,
                "mode": "apply",
                "status": "rolled_back",
                "backup_path": str(backup_path),
                "recalculated_cycles": recalculated,
                "unresolved_malformed_rows": unresolved,
                "failures": failures,
                "rollback": rollback,
            },
        )
        _summary(cycles, eligible, records, unresolved, failures, rollback)
        return 1

    _write_audit(
        audit_path,
        {
            **base_audit,
            "mode": "apply",
            "status": "verified",
            "backup_path": str(backup_path),
            "recalculated_cycles": recalculated,
            "unresolved_malformed_rows": [],
            "failures": [],
            "rollback": None,
        },
    )
    _summary(cycles, eligible, records, [], [])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
