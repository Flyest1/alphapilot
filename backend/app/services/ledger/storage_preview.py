"""Read-only publication preview against one account snapshot; never authorizes a write."""

from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import json

from pydantic import AwareDatetime, TypeAdapter

from app.models.account_ledger import Digest, Identifier, LedgerBalance, LedgerEvent
from app.services.ledger.reconciliation import reconcile_ledger
from app.services.ledger.replay import replay_ledger
from app.services.ledger.review import prepare_replay

MAX_SNAPSHOT_ITEMS = 10000


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def digest(value):
    return sha256(canonical(value).encode("utf-8")).hexdigest()


def proposed_import(batch, *, account_id, observed_at):
    """Same publication identity used by the existing import repository."""
    timestamp = TypeAdapter(AwareDatetime).validate_python(observed_at)
    events, errors = batch["events"], batch["errors"]
    result = {
        "errors": errors,
        "status": "partial" if errors and events else "validated" if events else "rejected",
        "coverage_verified": False,
    }
    manifest = {
        "document_hash": batch["document_hash"],
        "mapping_hash": batch["mapping_hash"],
        "schema_version": batch["schema_version"],
        "observed_at": timestamp.isoformat(),
        "source_type": "statement",
        "source_count": len(batch["sources"]),
        "coverage_verified": False,
    }
    return {
        "run_key": digest(
            {"manifest": manifest, "account_id": account_id, "events": events, "result": result}
        ),
        "manifest": manifest,
        "result": result,
        "events": events,
    }


def _time(value):
    return TypeAdapter(AwareDatetime).validate_python(value)


def _content(row):
    return {key: value for key, value in row.items() if key != "observed_at"}


def _snapshot(envelope, account):
    if not isinstance(envelope, dict) or set(envelope) != {"account_id", "snapshot"}:
        raise ValueError("Invalid snapshot envelope")
    if envelope["account_id"] != account:
        raise ValueError("Cross-account snapshot")
    snapshot = envelope["snapshot"]
    if not isinstance(snapshot, dict) or set(snapshot) != {"events", "imports", "reviews"}:
        raise ValueError("Invalid snapshot")
    if any(
        not isinstance(rows, list) or len(rows) > MAX_SNAPSHOT_ITEMS for rows in snapshot.values()
    ):
        raise ValueError("Invalid snapshot arrays")
    identities = {}
    for row in snapshot["events"]:
        event = LedgerEvent.model_validate(row)
        if event.account_id != account or (event.event_key, event.revision) in identities:
            raise ValueError("Invalid snapshot event identity")
        identities[(event.event_key, event.revision)] = row
    keys = set()
    for item in snapshot["imports"]:
        if not isinstance(item, dict) or set(item) != {"run_key", "manifest", "events", "result"}:
            raise ValueError("Invalid import snapshot")
        TypeAdapter(Digest).validate_python(item["run_key"])
        if (
            item["run_key"] in keys
            or not isinstance(item["events"], list)
            or len(item["events"]) > MAX_SNAPSHOT_ITEMS
        ):
            raise ValueError("Duplicate or invalid import")
        keys.add(item["run_key"])
        manifest = item["manifest"]
        _time(manifest["observed_at"])
        for key in ("document_hash", "mapping_hash"):
            TypeAdapter(Digest).validate_python(manifest[key])
        if (
            manifest["coverage_verified"] is not False
            or manifest["source_type"] != "statement"
            or type(manifest["source_count"]) is not int
            or manifest["source_count"] < 0
        ):
            raise ValueError("Invalid import manifest")
        if item["result"] is None:
            if item["events"]:
                raise ValueError("Unpublished import contains events")
            continue
        result = item["result"]
        if (
            result["coverage_verified"] is not False
            or result["status"] not in {"validated", "partial", "rejected"}
            or not isinstance(result["errors"], list)
            or len(item["events"]) + len(result["errors"]) != manifest["source_count"]
        ):
            raise ValueError("Invalid published import")
        expected = digest(
            {
                "manifest": manifest,
                "account_id": account,
                "events": item["events"],
                "result": result,
            }
        )
        if expected != item["run_key"]:
            raise ValueError("Import identity mismatch")
        for row in item["events"]:
            event = LedgerEvent.model_validate(row)
            stored = identities.get((event.event_key, event.revision))
            if (
                event.account_id != account
                or stored is None
                or _content(stored) != _content(row)
                or _time(stored["observed_at"]) > event.observed_at
            ):
                raise ValueError("Import event differs from stored evidence")
    review_ids = set()
    for review in snapshot["reviews"]:
        if not isinstance(review, dict) or review.get("account_id") != account:
            raise ValueError("Invalid review account")
        TypeAdapter(Digest).validate_python(review["review_key"])
        identity = (review["review_key"], review["revision"])
        if identity in review_ids:
            raise ValueError("Duplicate review identity")
        review_ids.add(identity)
        request = review["request"]
        if not isinstance(request, dict):
            raise ValueError("Invalid review request")
        kind, decision = request.get("kind"), request.get("decision")
        if kind == "duplicate_review":
            if set(request) != {
                "kind",
                "decision",
                "reason_code",
                "left_event_key",
                "right_event_key",
                "left_revision",
                "right_revision",
            }:
                raise ValueError("Invalid duplicate review fields")
            for side in ("left", "right"):
                TypeAdapter(Identifier).validate_python(request[side + "_event_key"])
                if type(request[side + "_revision"]) is not int or request[side + "_revision"] < 1:
                    raise ValueError("Invalid reviewed revision")
            if request["left_event_key"] >= request["right_event_key"]:
                raise ValueError("Invalid review pair order")
            reasons = {
                "duplicate": "same_transaction",
                "distinct": "separate_transactions",
                "reopen": "review_reopened",
            }
            if decision not in reasons or request["reason_code"] != reasons[decision]:
                raise ValueError("Invalid duplicate decision")
        elif kind == "import_resolution":
            if set(request) != {
                "kind",
                "decision",
                "reason_code",
                "source_run_key",
                "replacement_run_key",
            }:
                raise ValueError("Invalid import review fields")
            TypeAdapter(Digest).validate_python(request["source_run_key"])
            if decision == "resolve":
                TypeAdapter(Digest).validate_python(request["replacement_run_key"])
                if request["reason_code"] not in {"corrected_mapping", "retry_completed"}:
                    raise ValueError("Invalid resolution reason")
            elif (
                decision != "reopen"
                or request["replacement_run_key"] is not None
                or request["reason_code"] != "review_reopened"
            ):
                raise ValueError("Invalid resolution decision")
        else:
            raise ValueError("Unknown review kind")
        _time(review["reviewed_at"])
        if type(review["revision"]) is not int or review["revision"] < 1:
            raise ValueError("Invalid review revision")
    return {key: deepcopy(value) for key, value in snapshot.items()}


def preview_storage(context, envelope):
    try:
        return _preview(context, envelope)
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError("Invalid storage preview input") from exc


def _preview(context, envelope):
    account = TypeAdapter(Identifier).validate_python(context["account_id"])
    opening, closing = [
        LedgerBalance.model_validate(context[name]) for name in ("opening", "closing")
    ]
    if (
        opening.account_id != account
        or closing.account_id != account
        or closing.as_of.isoformat() != context["as_of"]
    ):
        raise ValueError("Invalid preview balance scope")
    known_at = _time(context["observed_at"])
    original = _snapshot(envelope, account)
    result = {
        "status": "blocked",
        "stored": False,
        "coverage_verified": False,
        "return_rate": None,
        "realized_profit_loss": None,
        "snapshot_hash": digest(envelope),
        "documents": [],
        "blockers": [],
        "duplicate_candidates": 0,
        "reconciliation": None,
    }
    merged = deepcopy(original)
    identities = {(row["event_key"], row["revision"]): row for row in merged["events"]}
    runs = {item["run_key"]: item for item in merged["imports"]}
    if not context["batches"] or len(context["batches"]) > 24:
        raise ValueError("Invalid proposal count")
    for index, batch in enumerate(context["batches"], 1):
        item = proposed_import(batch, account_id=account, observed_at=context["observed_at"])
        document = {
            "index": index,
            "run_key": item["run_key"],
            "status": "proposed",
            "new_events": 0,
            "new_revisions": 0,
            "reobserved_events": 0,
        }
        result["documents"].append(document)
        if batch["errors"] or not batch["events"]:
            result["blockers"].append({"code": "invalid_proposal", "document": index})
        if item["run_key"] in runs:
            existing = runs[item["run_key"]]
            if existing == item:
                document["status"] = "already_imported"
            else:
                document["status"] = "pending_or_conflicting_import"
                result["blockers"].append(
                    {"code": "pending_or_conflicting_import", "document": index}
                )
            continue
        conflict = False
        additions = {}
        for number, row in enumerate(batch["events"], 1):
            event = LedgerEvent.model_validate(row)
            if event.account_id != account or event.observed_at != known_at:
                raise ValueError("Proposal scope differs from preview")
            key = (event.event_key, event.revision)
            old = additions.get(key, identities.get(key))
            code = None
            if old is None:
                additions[key] = row
                document["new_events"] += 1
                if event.revision > 1:
                    document["new_revisions"] += 1
            elif _content(old) != _content(row):
                code = "conflicting_revision"
            elif _time(old["observed_at"]) > event.observed_at:
                code = "earlier_observation"
            else:
                document["reobserved_events"] += 1
            if code:
                conflict = True
                result["blockers"].append({"code": code, "document": index, "row": number})
        if conflict:
            document["status"] = "conflict"
            continue
        identities.update(additions)
        merged["events"].extend(additions.values())
        merged["imports"].append(item)
        runs[item["run_key"]] = item
    if len(merged["events"]) > MAX_SNAPSHOT_ITEMS:
        raise ValueError("Merged event limit exceeded")
    prepared = prepare_replay(
        merged,
        account_id=account,
        opening_date=opening.as_of.isoformat(),
        as_of=context["as_of"],
        known_at=known_at,
    )
    result["duplicate_candidates"] = len(prepared["duplicate_candidates"])
    if prepared["issues"]:
        result["blockers"].append({"code": "review_issues"})
    replay = replay_ledger(
        context["opening"], prepared["events"], as_of=context["as_of"], known_at=known_at
    )
    if replay["issues"]:
        result["blockers"].append({"code": "replay_issues"})
    comparison = reconcile_ledger(replay, context["closing"])
    comparison["issues"] = [{"reason": issue["reason"]} for issue in replay["issues"]]
    result["reconciliation"] = comparison
    if not comparison["balances_match"]:
        result["blockers"].append({"code": "balance_mismatch"})
    if not result["blockers"]:
        result["status"] = "ready_for_review"
    return json.loads(
        json.dumps(
            result,
            default=lambda v: format(v, "f") if isinstance(v, Decimal) else str(v),
            allow_nan=False,
        )
    )
