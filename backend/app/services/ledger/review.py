"""As-of review projection; never changes original imports or ledger events."""

from collections import defaultdict
from datetime import date
import json

from pydantic import AwareDatetime, TypeAdapter

from app.models.account_ledger import LedgerEvent
from app.services.ledger.replay import _event_day

IDENTITY_FIELDS = {
    "account_id",
    "event_key",
    "revision",
    "supersedes_hash",
    "source_type",
    "source_key",
    "source_record_hash",
    "observed_at",
    "quality",
}
REVIEWABLE_TYPES = {"trade", "deposit", "withdrawal", "dividend", "interest", "fx_conversion"}
MAX_CANDIDATES = 10000


def economic_signature(row):
    content = {key: value for key, value in row.items() if key not in IDENTITY_FIELDS}
    for key in ("quantity", "gross_amount", "fee", "tax", "net_cash_amount", "counter_amount"):
        value = content.get(key)
        if value is not None:
            value = value.rstrip("0").rstrip(".") if "." in value else value
            content[key] = "0" if value == "-0" else value
    return json.dumps(
        content,
        sort_keys=True,
        ensure_ascii=False,
    )


def prepare_replay(snapshot, *, account_id, opening_date, as_of, known_at):
    known_at = TypeAdapter(AwareDatetime).validate_python(known_at)
    if date.fromisoformat(opening_date) > date.fromisoformat(as_of):
        raise ValueError("Invalid review date window")
    models = [LedgerEvent.model_validate(row) for row in snapshot["events"]]
    if any(event.account_id != account_id for event in models):
        raise ValueError("Cross-account event in review snapshot")
    rows = [event.model_dump(mode="json") for event in models if event.observed_at <= known_at]
    imports = {
        item["run_key"]: item
        for item in snapshot["imports"]
        if TypeAdapter(AwareDatetime).validate_python(item["manifest"]["observed_at"]) <= known_at
    }
    latest = {}
    for item in snapshot["reviews"]:
        if TypeAdapter(AwareDatetime).validate_python(item["reviewed_at"]) > known_at:
            continue
        old = latest.get(item["review_key"])
        if old is None or item["revision"] > old["revision"]:
            latest[item["review_key"]] = item
    issues, replacements = [], {}
    for review in latest.values():
        request = review["request"]
        if request["kind"] != "import_resolution" or request["decision"] != "resolve":
            continue
        source, target = request["source_run_key"], request["replacement_run_key"]
        if source not in imports or target not in imports:
            continue
        original, replacement = imports[source], imports[target]
        publication = replacement["result"]
        if (
            source == target
            or not publication
            or publication["status"] != "validated"
            or publication["errors"]
            or original["manifest"]["document_hash"] != replacement["manifest"]["document_hash"]
            or original["manifest"]["source_count"] != replacement["manifest"]["source_count"]
            or len(replacement["events"]) != replacement["manifest"]["source_count"]
            or not replacement["events"]
        ):
            issues.append({"reason": "invalid_import_resolution", "run_key": source})
            continue
        replacements[source] = target
    # Follow chains defensively. Database also rejects cycles on write.
    resolved = set()
    for source in replacements:
        visited, cursor = set(), source
        while cursor in replacements and cursor not in visited:
            visited.add(cursor)
            cursor = replacements[cursor]
        if cursor in visited:
            issues.append({"reason": "cyclic_import_resolution", "run_key": source})
        else:
            resolved.add(source)
    active_heads = {}
    documents = defaultdict(set)
    for key, item in imports.items():
        if key in resolved:
            continue
        publication = item["result"]
        if publication is None or publication["status"] != "validated":
            issues.append({"reason": "incomplete_statement_import", "run_key": key})
        for event in item["events"]:
            if event["account_id"] != account_id:
                raise ValueError("Cross-account publication")
            if TypeAdapter(AwareDatetime).validate_python(event["observed_at"]) > known_at:
                continue
            event_key = event["event_key"]
            active_heads[event_key] = max(event["revision"], active_heads.get(event_key, 0))
            documents[(event_key, event["revision"])].add(item["manifest"]["document_hash"])
    # Retain prior revisions for the selected head's reversal chain, including a
    # previous revision from a resolved import. Obsolete unrelated keys disappear.
    selected = [row for row in rows if row["revision"] <= active_heads.get(row["event_key"], 0)]
    heads = {}
    for row in selected:
        try:
            if _event_day(LedgerEvent.model_validate(row)) > date.fromisoformat(as_of):
                continue
        except ValueError:
            continue
        old = heads.get(row["event_key"])
        if old is None or row["revision"] > old["revision"]:
            heads[row["event_key"]] = row
    by_signature = defaultdict(list)
    for key, row in heads.items():
        if row["event_type"] not in REVIEWABLE_TYPES or row["precision"] == "aggregate":
            continue
        try:
            day = _event_day(LedgerEvent.model_validate(row))
        except ValueError:
            continue  # The replay engine reports invalid date provenance.
        if date.fromisoformat(opening_date) < day <= date.fromisoformat(as_of):
            by_signature[economic_signature(row)].append(key)
    pair_reviews = {}
    for item in latest.values():
        request = item["request"]
        if request["kind"] == "duplicate_review":
            pair_reviews[(request["left_event_key"], request["right_event_key"])] = request
    candidates, exclusions, parent = [], set(), {key: key for key in heads}

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    limit_hit = False
    for group in by_signature.values():
        group.sort()
        for index, left in enumerate(group):
            for right in group[index + 1 :]:
                a, b = heads[left], heads[right]
                if not documents[(left, a["revision"])].isdisjoint(
                    documents[(right, b["revision"])]
                ):
                    continue
                if len(candidates) >= MAX_CANDIDATES:
                    limit_hit = True
                    break
                request = pair_reviews.get((left, right))
                decision = "unreviewed"
                if (
                    request
                    and request["left_revision"] == a["revision"]
                    and request["right_revision"] == b["revision"]
                    and request["decision"] != "reopen"
                ):
                    decision = request["decision"]
                candidate = {
                    "left_event_key": left,
                    "left_revision": a["revision"],
                    "right_event_key": right,
                    "right_revision": b["revision"],
                    "decision": decision,
                }
                candidates.append(candidate)
                if decision == "duplicate":
                    first, second = sorted((find(left), find(right)))
                    parent[second] = first
                elif decision == "unreviewed":
                    issues.append({"reason": "unreviewed_duplicate_candidate", **candidate})
            if limit_hit:
                break
        if limit_hit:
            break
    conflicting = set()
    for item in candidates:
        if item["decision"] == "distinct" and find(item["left_event_key"]) == find(
            item["right_event_key"]
        ):
            conflicting.add(find(item["left_event_key"]))
    if conflicting:
        issues.append({"reason": "conflicting_duplicate_reviews"})
    if limit_hit:
        issues.append({"reason": "duplicate_candidate_limit_exceeded"})
    else:
        for key in heads:
            if find(key) != key and find(key) not in conflicting:
                exclusions.add(key)
    return {
        "events": [row for row in selected if row["event_key"] not in exclusions],
        "issues": issues,
        "resolved_imports": sorted(resolved),
        "excluded_event_keys": sorted(exclusions),
        "duplicate_candidates": candidates,
        "review_history": sorted(latest.values(), key=lambda item: item["review_key"]),
        "imports": [
            {"run_key": key, "manifest": item["manifest"], "result": item["result"]}
            for key, item in sorted(imports.items())
        ],
        "coverage_verified": False,
    }
