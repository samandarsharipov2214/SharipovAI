from news_monitor.source_independence import evaluate_event_independence


def _event():
    return {
        "event_id": "event-1",
        "source_families": ("wire-a", "publisher-b", "publisher-c"),
        "provenance_ids": ("prov-a", "prov-b", "prov-c"),
    }


def test_distinct_families_same_origin_do_not_confirm_independence():
    result = evaluate_event_independence(
        _event(),
        [
            {
                "event_id": "event-1",
                "source_family": "wire-a",
                "provenance_id": "prov-a",
                "origin_group": "origin-wire-a",
                "verification_status": "verified",
            },
            {
                "event_id": "event-1",
                "source_family": "publisher-b",
                "provenance_id": "prov-b",
                "origin_group": "origin-wire-a",
                "verification_status": "verified",
            },
        ],
    )

    assert result["status"] == "INSUFFICIENT_INDEPENDENCE"
    assert result["independently_confirmed"] is False
    assert result["independent_origin_count"] == 1
    assert result["execution_authority"] is False


def test_verified_distinct_origins_confirm_event():
    result = evaluate_event_independence(
        _event(),
        [
            {
                "event_id": "event-1",
                "source_family": "wire-a",
                "provenance_id": "prov-a",
                "origin_group": "origin-wire-a",
                "verification_status": "verified",
            },
            {
                "event_id": "event-1",
                "source_family": "publisher-b",
                "provenance_id": "prov-b",
                "origin_group": "origin-publisher-b",
                "verification_status": "verified",
            },
        ],
    )

    assert result["status"] == "CONFIRMED"
    assert result["independently_confirmed"] is True
    assert result["independent_origin_count"] == 2
    assert result["origin_groups"] == ("origin-publisher-b", "origin-wire-a")


def test_unverified_or_mismatched_attestations_fail_closed():
    result = evaluate_event_independence(
        _event(),
        [
            {
                "event_id": "event-1",
                "source_family": "wire-a",
                "provenance_id": "prov-a",
                "origin_group": "origin-a",
                "verification_status": "claimed",
            },
            {
                "event_id": "different-event",
                "source_family": "publisher-b",
                "provenance_id": "prov-b",
                "origin_group": "origin-b",
                "verification_status": "verified",
            },
            {
                "event_id": "event-1",
                "source_family": "publisher-c",
                "provenance_id": "unknown-provenance",
                "origin_group": "origin-c",
                "verification_status": "verified",
            },
        ],
    )

    assert result["independently_confirmed"] is False
    assert result["independent_origin_count"] == 0
    assert result["rejected_attestation_count"] == 3


def test_processing_is_bounded_and_truncation_is_explicit():
    attestations = [
        {
            "event_id": "event-1",
            "source_family": "wire-a",
            "provenance_id": "prov-a",
            "origin_group": f"origin-{index}",
            "verification_status": "verified",
        }
        for index in range(8)
    ]

    result = evaluate_event_independence(_event(), attestations, max_attestations=3)

    assert result["processed_attestation_count"] == 3
    assert result["truncated"] is True
    assert result["max_attestations"] == 3


def test_invalid_configuration_is_rejected():
    try:
        evaluate_event_independence(_event(), [], min_independent_origins=1)
    except ValueError as exc:
        assert "at least 2" in str(exc)
    else:
        raise AssertionError("expected minimum independence validation")

    try:
        evaluate_event_independence(_event(), [], max_attestations=0)
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("expected bounded-attestation validation")
