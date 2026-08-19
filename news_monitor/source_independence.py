"""Conservative source-independence confirmation for clustered news events.

Distinct publisher families are useful provenance, but they are not proof of
independent reporting.  This module therefore requires explicit, verified
origin-group attestations before an event can be described as independently
confirmed.  It is advisory evidence only and has no execution authority.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

DEFAULT_MAX_ATTESTATIONS = 64
DEFAULT_MIN_INDEPENDENT_ORIGINS = 2


def evaluate_event_independence(
    event: Mapping[str, Any],
    attestations: Sequence[Mapping[str, Any]],
    *,
    min_independent_origins: int = DEFAULT_MIN_INDEPENDENT_ORIGINS,
    max_attestations: int = DEFAULT_MAX_ATTESTATIONS,
) -> dict[str, object]:
    """Evaluate explicit source-independence evidence for one clustered event.

    A publisher/source family is never treated as independent merely because its
    name differs.  Only attestations with ``verification_status == \"verified\"``
    and a non-empty ``origin_group`` can contribute.  Multiple families that
    trace back to the same origin group count once.
    """

    event_id = str(event.get("event_id") or "").strip()
    if not event_id:
        raise ValueError("event requires event_id")

    threshold = int(min_independent_origins)
    if threshold < 2:
        raise ValueError("min_independent_origins must be at least 2")
    limit = int(max_attestations)
    if limit < 1:
        raise ValueError("max_attestations must be positive")

    source_families = {
        str(value).strip()
        for value in (event.get("source_families") or ())
        if str(value).strip()
    }
    provenance_ids = {
        str(value).strip()
        for value in (event.get("provenance_ids") or ())
        if str(value).strip()
    }

    selected = list(attestations[:limit])
    accepted: list[dict[str, str]] = []
    rejected_count = 0
    origin_groups: set[str] = set()

    for row in selected:
        if str(row.get("event_id") or "").strip() != event_id:
            rejected_count += 1
            continue
        if str(row.get("verification_status") or "").strip().casefold() != "verified":
            rejected_count += 1
            continue

        family = str(row.get("source_family") or "").strip()
        provenance_id = str(row.get("provenance_id") or "").strip()
        origin_group = str(row.get("origin_group") or "").strip()

        if not family or family not in source_families:
            rejected_count += 1
            continue
        if provenance_ids and (not provenance_id or provenance_id not in provenance_ids):
            rejected_count += 1
            continue
        if not origin_group:
            rejected_count += 1
            continue

        accepted.append(
            {
                "source_family": family,
                "provenance_id": provenance_id,
                "origin_group": origin_group,
            }
        )
        origin_groups.add(origin_group)

    independent_count = len(origin_groups)
    confirmed = independent_count >= threshold
    return {
        "event_id": event_id,
        "status": "CONFIRMED" if confirmed else "INSUFFICIENT_INDEPENDENCE",
        "independently_confirmed": confirmed,
        "independent_origin_count": independent_count,
        "required_independent_origin_count": threshold,
        "origin_groups": tuple(sorted(origin_groups)),
        "accepted_attestations": tuple(accepted),
        "processed_attestation_count": len(selected),
        "rejected_attestation_count": rejected_count,
        "truncated": len(attestations) > limit,
        "max_attestations": limit,
        "execution_authority": False,
    }


__all__ = [
    "DEFAULT_MAX_ATTESTATIONS",
    "DEFAULT_MIN_INDEPENDENT_ORIGINS",
    "evaluate_event_independence",
]
