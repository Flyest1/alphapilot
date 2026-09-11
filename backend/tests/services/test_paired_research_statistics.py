from app.services.paired_research_statistics import paired_research_statistics


def observations(count=35, tickers=("A",)):
    from datetime import date, timedelta

    return [
        {
            "date": (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
            "market": "US",
            "ticker": ticker,
            "label_end_date": (date(2026, 1, 2) + timedelta(days=index)).isoformat(),
            "net_return_pct": float(index % 7),
            "status": "evaluated",
        }
        for index in range(count)
        for ticker in tickers
    ]


def test_identical_pairs_have_zero_difference_interval():
    rows = observations()
    result = paired_research_statistics(rows, rows)
    assert result["status"] == "available"
    assert result["mean_difference_pct"] == 0
    assert result["interval_pct"] == [0, 0]
    assert result["crosses_zero"] is True
    assert result["comparison_count"] == 8


def test_stocks_on_one_date_do_not_count_as_independent_cohorts():
    rows = observations(1, tuple(str(index) for index in range(40)))
    result = paired_research_statistics(rows, rows)
    assert result["paired_record_count"] == 40
    assert result["cohort_count"] == 1
    assert result["status"] == "insufficient_data"
    assert result["interval_pct"] is None


def test_shuffled_inputs_produce_identical_seeded_intervals():
    champion = observations(40, ("A", "B"))
    model = [{**row, "net_return_pct": row["net_return_pct"] * 1.3 + 0.5} for row in champion]
    assert paired_research_statistics(model, champion) == paired_research_statistics(
        model[::-1], champion[17:] + champion[:17]
    )


def test_missing_counterparts_pending_and_excluded_do_not_enter_pairs():
    model = observations()
    champion = observations()[1:]
    model[2]["status"] = "pending"
    champion[3]["status"] = "excluded"
    result = paired_research_statistics(model, champion)
    assert result["paired_record_count"] == 32
    assert result["eligible_model_count"] == 34
    assert result["eligible_champion_count"] == 33
    assert result["model_pair_coverage"] == 32 / 34
    assert result["champion_pair_coverage"] == 32 / 33


def test_small_samples_report_no_interval_or_sign_claim():
    rows = observations(29)
    result = paired_research_statistics(rows, rows)
    assert result["status"] == "insufficient_data"
    assert result["interval_pct"] is None
    assert result["crosses_zero"] is None


def test_matching_requires_market_ticker_and_label_end():
    rows = observations(3)
    other = [dict(row) for row in rows]
    other[0]["market"] = "KR"
    other[1]["ticker"] = "OTHER"
    other[2]["label_end_date"] = "2026-03-01"
    result = paired_research_statistics(rows, other)
    assert result["paired_record_count"] == 0
    assert result["mean_difference_pct"] is None


def test_equal_date_weighting_and_explicit_idle_opportunity_cost():
    champion = observations(2, ("A", "B"))[:3]
    model = [{**row, "net_return_pct": 10.0} for row in champion]
    model[2]["status"] = "idle"
    model[2]["net_return_pct"] = 0
    champion = [{**row, "net_return_pct": 0.0} for row in champion]
    result = paired_research_statistics(model, champion)
    assert result["mean_difference_pct"] == 5
    assert result["paired_record_count"] == 3
    assert result["cohort_count"] == 2


def test_unknown_status_and_duplicate_identities_are_explicitly_excluded():
    rows = observations(3)
    rows[2].pop("status")
    result = paired_research_statistics(rows + [rows[0]], observations(3))
    assert result["paired_record_count"] == 1
    assert result["model_exclusions"] == {"duplicate_key": 2, "unknown_status": 1}


def test_fixed_positive_difference_interval_does_not_cross_zero():
    champion = observations()
    model = [{**row, "net_return_pct": row["net_return_pct"] + 2} for row in champion]
    result = paired_research_statistics(model, champion)
    assert result["interval_pct"] == [2, 2]
    assert result["crosses_zero"] is False


def test_accepts_challenger_runner_observation_shape():
    champion = {
        "ticker": "AAPL",
        "market": "US",
        "date": "2026-01-02",
        "label_end_date": "2026-02-03",
        "entry_date": "2026-01-05",
        "score": 70,
        "champion_action": "BUY",
        "active": True,
        "status": "evaluated",
        "outcome": "expired",
        "gross_return_pct": 4.0,
        "net_return_pct": 3.5,
        "cost_pct": 0.5,
    }
    challenger = {**champion, "active": False, "status": "idle", "net_return_pct": 0.0}
    result = paired_research_statistics([challenger], [champion])
    assert result["cohort_count"] == 1
    assert result["paired_record_count"] == 1
    assert result["mean_difference_pct"] == -3.5
