from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.db.supabase_client import InMemoryRepository
from app.models.advisory import parse_advisory_job_request, validate_advisory_result
from app.services.advisory.job_service import (
    AdvisoryDispatcher,
    AdvisoryJobStore,
    run_advisory_job,
)


def test_all_supported_advisory_request_types_validate_strictly():
    payloads = [
        {"analysis_type": "undervalued_us_stocks"},
        {"analysis_type": "etf_rebalancing", "positions": [{"ticker": "VT"}]},
        {"analysis_type": "post_earnings_opportunities"},
        {"analysis_type": "ai_beneficiaries"},
        {"analysis_type": "high_dividend_etfs"},
        {"analysis_type": "sec_filing_risk", "ticker": "AAPL"},
        {"analysis_type": "etf_overlap", "positions": [{"ticker": "VOO", "weight_pct": 60}]},
        {"analysis_type": "sector_outlook", "custom_proxies": {"technology": "XLK"}},
    ]

    for payload in payloads:
        request = parse_advisory_job_request(payload)
        assert request.analysis_type == payload["analysis_type"]

    with pytest.raises(ValidationError):
        parse_advisory_job_request(
            {"analysis_type": "ai_beneficiaries", "unexpected_parameter": True}
        )

    with pytest.raises(ValidationError):
        parse_advisory_job_request({"analysis_type": "sec_filing_risk", "tickers": ["AAPL"]})

    with pytest.raises(ValidationError):
        parse_advisory_job_request({"analysis_type": "etf_overlap", "positions": []})


def test_advisory_result_contract_rejects_missing_required_feature_fields():
    with pytest.raises(ValidationError):
        validate_advisory_result(
            {
                "analysis_type": "sector_outlook",
                "evidence": [],
                "data_quality": {},
                "disclaimer": "투자 의사결정 지원 정보입니다.",
            }
        )


def test_advisory_job_store_reuses_active_request_hash():
    store = AdvisoryJobStore(InMemoryRepository())
    request = parse_advisory_job_request(
        {"analysis_type": "undervalued_us_stocks", "max_results": 5}
    )

    first, first_created = store.create_or_get_active(request)
    second, second_created = store.create_or_get_active(request)

    assert first_created is True
    assert second_created is False
    assert second.job_id == first.job_id
    assert second.request_hash == first.request_hash


def test_advisory_job_store_expires_stale_active_request_before_recreating():
    repository = InMemoryRepository()
    request = parse_advisory_job_request({"analysis_type": "sector_outlook"})
    stale = repository.create_advisory_job(
        {
            "analysis_type": request.analysis_type,
            "request_payload": request.model_dump(mode="json"),
            "request_hash": "a" * 64,
            "status": "running",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    )
    store = AdvisoryJobStore(repository, active_timeout=timedelta(minutes=20))

    created, was_created = store.create_or_get_active(request)
    expired = store.get(stale["job_id"])

    assert was_created is True
    assert created.job_id != stale["job_id"]
    assert expired is not None
    assert expired.status == "failed"
    assert expired.error_code == "stale_active_job"


def test_unregistered_analysis_fails_with_safe_unsupported_code():
    store = AdvisoryJobStore(InMemoryRepository())
    job, _created = store.create_or_get_active(
        parse_advisory_job_request(
            {"analysis_type": "etf_overlap", "positions": [{"ticker": "VT"}]}
        )
    )

    run_advisory_job(store, AdvisoryDispatcher(), job.job_id)

    failed = store.get(job.job_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error_code == "unsupported_analysis"
    assert failed.step_timings["analysis"]["status"] == "failed"
    assert "etf_overlap" not in (failed.message or "")


def test_registered_dispatcher_persists_completed_analysis():
    store = AdvisoryJobStore(InMemoryRepository())
    job, _created = store.create_or_get_active(
        parse_advisory_job_request({"analysis_type": "ai_beneficiaries", "themes": ["chips"]})
    )

    def handler(_job, request):
        return {
            "analysis_type": request.analysis_type,
            "rows": [],
            "verified_ai_beneficiaries": [],
            "ai_theme_caution": [],
            "evidence": [],
            "data_quality": {"status": "partial"},
            "disclaimer": "투자 의사결정 지원 정보입니다.",
        }

    run_advisory_job(store, AdvisoryDispatcher({"ai_beneficiaries": handler}), job.job_id)

    completed = store.get(job.job_id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.analysis_id is not None
    assert completed.step_timings["analysis"]["status"] == "completed"
    analysis = store.get_analysis(completed.analysis_id)
    assert analysis is not None
    assert analysis.result["analysis_type"] == "ai_beneficiaries"
    assert analysis.result["verified_ai_beneficiaries"] == []
