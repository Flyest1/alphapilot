from copy import deepcopy
from datetime import datetime

from app.models.account_ledger import LedgerEvent
from app.services.ledger.review import prepare_replay

NOW = datetime.fromisoformat("2026-09-23T12:00:00+09:00")


def event(key="one", document="a"):
    return LedgerEvent.model_validate(
        {
            "account_id": "demo",
            "event_key": key,
            "source_type": "statement",
            "source_key": document * 64 + ":1",
            "source_record_hash": "f" * 64,
            "event_type": "deposit",
            "event_date": "2026-09-10",
            "observed_at": "2026-09-11T00:00:00Z",
            "timezone": "Asia/Seoul",
            "precision": "date_only",
            "quality": "verified",
            "currency": "USD",
            "gross_amount": "10",
            "fee": "0",
            "tax": "0",
            "net_cash_amount": "10",
        }
    ).model_dump(mode="json")


def imported(key, rows, *, document="a", status="validated"):
    return {
        "run_key": key,
        "manifest": {
            "document_hash": document * 64,
            "observed_at": "2026-09-11T00:00:00Z",
            "source_count": 1,
        },
        "events": rows,
        "result": {"status": status, "errors": []},
    }


def review(request, revision=1, when="2026-09-22T00:00:00Z", key="review"):
    return {"review_key": key, "revision": revision, "reviewed_at": when, "request": request}


def prepare(events, imports, reviews=(), known_at=NOW):
    return prepare_replay(
        {"events": events, "imports": imports, "reviews": reviews},
        account_id="demo",
        opening_date="2026-08-31",
        as_of="2026-09-23",
        known_at=known_at,
    )


def test_resolution_replaces_obsolete_event_keys_but_keeps_original_snapshot():
    old, new = event("old"), event("new")
    imports = [imported("bad", [old], status="partial"), imported("good", [new])]
    decision = review(
        {
            "kind": "import_resolution",
            "source_run_key": "bad",
            "replacement_run_key": "good",
            "decision": "resolve",
        }
    )
    saved = deepcopy(imports)
    result = prepare([old, new], imports, [decision])
    assert [row["event_key"] for row in result["events"]] == ["new"]
    assert not result["issues"] and result["resolved_imports"] == ["bad"]
    assert imports == saved
    earlier = prepare(
        [old, new], imports, [decision], datetime.fromisoformat("2026-09-21T00:00:00+00:00")
    )
    assert any(issue["reason"] == "incomplete_statement_import" for issue in earlier["issues"])


def test_reopen_restores_incomplete_status():
    row = event()
    request = {
        "kind": "import_resolution",
        "source_run_key": "bad",
        "replacement_run_key": "good",
        "decision": "resolve",
    }
    reopened = {**request, "replacement_run_key": None, "decision": "reopen"}
    result = prepare(
        [row],
        [imported("bad", [row], status="partial"), imported("good", [row])],
        [review(request), review(reopened, 2)],
    )
    assert result["resolved_imports"] == [] and result["issues"]


def pair(decision="duplicate", left="a", right="b"):
    return {
        "kind": "duplicate_review",
        "left_event_key": left,
        "left_revision": 1,
        "right_event_key": right,
        "right_revision": 1,
        "decision": decision,
    }


def test_cross_document_candidates_never_auto_delete_and_explicit_review_deduplicates():
    a, b = event("a", "a"), event("b", "b")
    imports = [imported("one", [a]), imported("two", [b], document="b")]
    unresolved = prepare([a, b], imports)
    assert len(unresolved["events"]) == 2 and len(unresolved["duplicate_candidates"]) == 1
    assert unresolved["issues"][0]["reason"] == "unreviewed_duplicate_candidate"
    distinct = prepare([a, b], imports, [review(pair("distinct"))])
    assert len(distinct["events"]) == 2 and not distinct["issues"]
    duplicate = prepare([a, b], imports, [review(pair())])
    assert [row["event_key"] for row in duplicate["events"]] == ["a"]
    assert duplicate["excluded_event_keys"] == ["b"] and not duplicate["issues"]


def test_same_document_identical_rows_are_not_duplicate_candidates():
    a, b = event("a"), event("b")
    b["source_key"] = "a" * 64 + ":2"
    result = prepare([a, b], [imported("one", [a, b])])
    assert not result["duplicate_candidates"] and len(result["events"]) == 2


def test_equivalent_decimal_spellings_are_duplicate_candidates():
    a, b = event("a", "a"), event("b", "b")
    b.update(gross_amount="10.0000", fee="0.00", tax="-0.000", net_cash_amount="10.00")
    result = prepare([a, b], [imported("one", [a]), imported("two", [b], document="b")])
    assert len(result["duplicate_candidates"]) == 1


def test_future_effective_revision_does_not_hide_historical_duplicate():
    a, b = event("a", "a"), event("b", "b")
    future = {
        **a,
        "revision": 2,
        "supersedes_hash": a["source_record_hash"],
        "source_record_hash": "e" * 64,
        "event_date": "2026-09-24",
        "observed_at": "2026-09-24T00:00:00Z",
        "gross_amount": "20",
        "net_cash_amount": "20",
    }
    # Known later, replay cutoff still the day before the correction's event.
    imports = [imported("one", [a, future]), imported("two", [b], document="b")]
    result = prepare(
        [a, b, future], imports, known_at=datetime.fromisoformat("2026-09-25T00:00:00+00:00")
    )
    assert len(result["duplicate_candidates"]) == 1
    assert result["duplicate_candidates"][0]["left_revision"] == 1


def test_contradictory_duplicate_component_retains_all_events():
    events = [event(key, key) for key in "abc"]
    imports = [imported(key, [row], document=key) for key, row in zip("abc", events)]
    reviews = [
        review(pair(left="a", right="b"), key="ab"),
        review(pair(left="b", right="c"), key="bc"),
        review(pair("distinct", "a", "c"), key="ac"),
    ]
    result = prepare(events, imports, reviews)
    assert len(result["events"]) == 3
    assert any(issue["reason"] == "conflicting_duplicate_reviews" for issue in result["issues"])
