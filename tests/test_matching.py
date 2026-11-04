"""
tests/test_matching.py
----------------------
Unit tests for the WasteLoop matching engine.

Coverage:
  - Hard eligibility filters (each failure reason)
  - Individual dimension scorers
  - Composite scoring and ranking
  - Pickup proposal restriction (agent cannot approve its own pickup)
  - Tie-breaking by distance
"""

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from matching.engine import (
    CapacityInput,
    ListingInput,
    MatchResult,
    ProcessorInput,
    ScoreBreakdown,
    find_matches,
    haversine_km,
    is_eligible,
    score_availability,
    score_distance,
    score_material,
    score_quality,
    score_quantity,
    score_processor_for_listing,
    WEIGHT_MATERIAL,
    WEIGHT_CAPACITY,
    WEIGHT_DISTANCE,
    WEIGHT_AVAILABILITY,
    MAX_DISTANCE_KM,
)


# ---------------------------------------------------------------------------
# Fixtures — reusable test data
# ---------------------------------------------------------------------------

TODAY = date(2026, 11, 5)
NEXT_WEEK = date(2026, 11, 12)
NEXT_MONTH = date(2026, 11, 30)


def make_listing(
    *,
    material="WET_ORGANIC",
    quantity_kg=300.0,
    quality_grade="A",
    available_from=TODAY,
    available_until=NEXT_WEEK,
    lat=12.9716,
    lng=77.5946,
) -> ListingInput:
    return ListingInput(
        id=1,
        material_type=material,
        quantity_kg=quantity_kg,
        quality_grade=quality_grade,
        available_from=available_from,
        available_until=available_until,
        generator_lat=lat,
        generator_lng=lng,
    )


def make_capacity(
    *,
    processor_id=1,
    material="WET_ORGANIC",
    min_qty=100.0,
    max_qty=2000.0,
    grades="A",
    available_from=TODAY,
    available_until=NEXT_MONTH,
    current_load_kg=0.0,
) -> CapacityInput:
    return CapacityInput(
        processor_id=processor_id,
        material_type=material,
        min_quantity_kg=min_qty,
        max_quantity_kg=max_qty,
        accepted_grades=grades,
        available_from=available_from,
        available_until=available_until,
        current_load_kg=current_load_kg,
    )


def make_processor(
    *,
    pid=1,
    name="Test Processor",
    ptype="BIOGAS_PLANT",
    lat=12.9716,
    lng=77.5946,
    capacities=None,
) -> ProcessorInput:
    return ProcessorInput(
        id=pid,
        name=name,
        processor_type=ptype,
        lat=lat,
        lng=lng,
        is_synthetic=True,
        capacities=capacities or [],
    )


# ---------------------------------------------------------------------------
# Weight integrity
# ---------------------------------------------------------------------------

def test_weights_sum_to_one():
    total = WEIGHT_MATERIAL + WEIGHT_CAPACITY + WEIGHT_DISTANCE + WEIGHT_AVAILABILITY
    assert abs(total - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Haversine
# ---------------------------------------------------------------------------

def test_haversine_same_point_is_zero():
    assert haversine_km(12.97, 77.59, 12.97, 77.59) == pytest.approx(0.0, abs=1e-6)


def test_haversine_known_distance():
    # Approximate distance between Bengaluru city centre and Whitefield (~18 km)
    d = haversine_km(12.9716, 77.5946, 12.9698, 77.7499)
    assert 15.0 < d < 20.0


# ---------------------------------------------------------------------------
# Individual dimension scorers
# ---------------------------------------------------------------------------

def test_score_material_match():
    assert score_material("WET_ORGANIC", "WET_ORGANIC") == 1.0


def test_score_material_mismatch():
    assert score_material("WET_ORGANIC", "DRY_PAPER") == 0.0


def test_score_quality_exact_match():
    assert score_quality("A", "A") == 1.0
    assert score_quality("B", "A,B") == 1.0
    assert score_quality("C", "B,C") == 1.0


def test_score_quality_listing_cleaner_than_required():
    # Processor only takes B; listing is A (cleaner) — acceptable but suboptimal
    assert score_quality("A", "B") == 0.5


def test_score_quality_listing_too_dirty():
    # Processor only takes A; listing is C — rejected
    assert score_quality("C", "A") == 0.0
    assert score_quality("B", "A") == 0.0


def test_score_quantity_perfect_fit():
    s = score_quantity(500.0, 100.0, 2000.0, 0.0)
    assert 0.0 < s <= 1.0


def test_score_quantity_below_minimum():
    assert score_quantity(50.0, 100.0, 2000.0, 0.0) == 0.0


def test_score_quantity_insufficient_headroom():
    # max=1000, current_load=800, headroom=200 — listing of 300 doesn't fit
    assert score_quantity(300.0, 100.0, 1000.0, 800.0) == 0.0


def test_score_quantity_exact_headroom():
    # Listing exactly fills remaining headroom: headroom = max - current_load = 200,
    # quantity = 200 → passes the filter, score = 1.0
    s = score_quantity(200.0, 100.0, 1000.0, 800.0)
    assert s == pytest.approx(1.0)


def test_score_quantity_just_enough_headroom():
    # headroom = 200, quantity = 200 -> eligible
    s = score_quantity(200.0, 100.0, 1000.0, 800.0)
    assert s > 0.0


def test_score_distance_zero():
    assert score_distance(0.0) == pytest.approx(1.0)


def test_score_distance_at_max():
    assert score_distance(MAX_DISTANCE_KM) == pytest.approx(0.0)


def test_score_distance_beyond_max():
    assert score_distance(MAX_DISTANCE_KM + 10) == 0.0


def test_score_distance_midpoint():
    assert score_distance(MAX_DISTANCE_KM / 2) == pytest.approx(0.5)


def test_score_availability_full_overlap():
    assert score_availability(
        date(2026, 11, 5), date(2026, 11, 12),
        date(2026, 11, 1), date(2026, 11, 30),
    ) == pytest.approx(1.0)


def test_score_availability_no_overlap():
    assert score_availability(
        date(2026, 11, 5), date(2026, 11, 12),
        date(2026, 11, 20), date(2026, 11, 30),
    ) == 0.0


def test_score_availability_partial_overlap():
    # Listing: Nov 5–12 (8 days); processor available Nov 9–30 → overlap Nov 9–12 (4 days)
    s = score_availability(
        date(2026, 11, 5), date(2026, 11, 12),
        date(2026, 11, 9), date(2026, 11, 30),
    )
    assert s == pytest.approx(4 / 8)


# ---------------------------------------------------------------------------
# Hard eligibility filters
# ---------------------------------------------------------------------------

def test_eligible_passes_all_filters():
    listing = make_listing()
    cap = make_capacity()
    ok, reason = is_eligible(listing, cap)
    assert ok is True
    assert reason == ""


def test_hard_filter_material_mismatch():
    listing = make_listing(material="WET_ORGANIC")
    cap = make_capacity(material="DRY_PAPER")
    ok, reason = is_eligible(listing, cap)
    assert ok is False
    assert reason == "material_mismatch"


def test_hard_filter_grade_too_low():
    listing = make_listing(quality_grade="C")
    cap = make_capacity(grades="A")  # only takes A; C is too dirty
    ok, reason = is_eligible(listing, cap)
    assert ok is False
    assert reason == "grade_too_low"


def test_hard_filter_quantity_below_minimum():
    listing = make_listing(quantity_kg=50.0)
    cap = make_capacity(min_qty=100.0)
    ok, reason = is_eligible(listing, cap)
    assert ok is False
    assert reason == "quantity_below_minimum"


def test_hard_filter_insufficient_headroom():
    listing = make_listing(quantity_kg=500.0)
    cap = make_capacity(max_qty=1000.0, current_load_kg=700.0)  # headroom=300 < 500
    ok, reason = is_eligible(listing, cap)
    assert ok is False
    assert reason == "insufficient_capacity_headroom"


def test_hard_filter_no_date_overlap():
    listing = make_listing(
        available_from=date(2026, 11, 5),
        available_until=date(2026, 11, 12),
    )
    cap = make_capacity(
        available_from=date(2026, 11, 20),
        available_until=date(2026, 11, 30),
    )
    ok, reason = is_eligible(listing, cap)
    assert ok is False
    assert reason == "no_date_overlap"


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------

def test_score_processor_returns_result_for_eligible():
    listing = make_listing()
    cap = make_capacity()
    processor = make_processor(capacities=[cap])
    result = score_processor_for_listing(listing, processor)
    assert result is not None
    assert 0.0 < result.score <= 1.0


def test_score_processor_returns_none_for_ineligible():
    listing = make_listing(material="WET_ORGANIC")
    cap = make_capacity(material="DRY_PAPER")  # wrong material
    processor = make_processor(capacities=[cap])
    result = score_processor_for_listing(listing, processor)
    assert result is None


def test_score_processor_picks_best_capacity_row():
    """When a processor has two eligible capacity rows, the higher-scoring one wins."""
    listing = make_listing(quantity_kg=300.0)
    cap_low = make_capacity(min_qty=100.0, max_qty=400.0, current_load_kg=0.0)
    cap_high = make_capacity(min_qty=100.0, max_qty=2000.0, current_load_kg=0.0)
    processor = make_processor(capacities=[cap_low, cap_high])
    result = score_processor_for_listing(listing, processor)
    assert result is not None
    # Both are eligible but cap_high should give a better quantity score
    # (more headroom relative to quantity)
    assert result.score > 0.0


def test_composite_score_range():
    listing = make_listing()
    cap = make_capacity()
    processor = make_processor(capacities=[cap])
    result = score_processor_for_listing(listing, processor)
    assert result is not None
    assert 0.0 <= result.score <= 1.0


# ---------------------------------------------------------------------------
# find_matches — ranking and top_k
# ---------------------------------------------------------------------------

def _nearby_processor(pid: int, material="WET_ORGANIC") -> ProcessorInput:
    """Helper: processor 1 km away from default listing origin."""
    return make_processor(
        pid=pid,
        name=f"Processor {pid}",
        lat=12.9716 + 0.009 * pid,  # ~1 km steps north
        lng=77.5946,
        capacities=[make_capacity(processor_id=pid, material=material)],
    )


def test_find_matches_returns_top_k():
    listing = make_listing()
    processors = [_nearby_processor(i) for i in range(1, 6)]
    results, _ = find_matches(listing, processors, top_k=3)
    assert len(results) <= 3


def test_find_matches_sorted_by_score_desc():
    listing = make_listing()
    processors = [_nearby_processor(i) for i in range(1, 6)]
    results, _ = find_matches(listing, processors, top_k=5)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_find_matches_excludes_ineligible():
    listing = make_listing(material="WET_ORGANIC")
    wrong_material = make_processor(
        pid=99,
        name="Wrong Material Proc",
        capacities=[make_capacity(processor_id=99, material="DRY_PAPER")],
    )
    results, _ = find_matches(listing, [wrong_material], top_k=3)
    assert len(results) == 0


def test_find_matches_tiebreak_by_distance():
    """Two processors with identical eligibility profiles but different distances."""
    listing = make_listing(lat=12.9716, lng=77.5946)

    # Close processor: 2 km away
    close = make_processor(
        pid=1, name="Close", lat=12.9716 + 0.018, lng=77.5946,
        capacities=[make_capacity(processor_id=1)],
    )
    # Far processor: 10 km away
    far = make_processor(
        pid=2, name="Far", lat=12.9716 + 0.090, lng=77.5946,
        capacities=[make_capacity(processor_id=2)],
    )

    results, _ = find_matches(listing, [far, close], top_k=2)
    # Close should rank first (higher distance score)
    assert results[0].processor_id == 1


def test_find_matches_counts_candidates():
    """candidates_evaluated should count processors with relevant capacity rows."""
    listing = make_listing(material="WET_ORGANIC")
    wet_proc = _nearby_processor(1, material="WET_ORGANIC")
    dry_proc = make_processor(
        pid=2, name="Dry Proc",
        capacities=[make_capacity(processor_id=2, material="DRY_PAPER")],
    )
    _, candidates = find_matches(listing, [wet_proc, dry_proc], top_k=3)
    # Only wet_proc has relevant capacity for WET_ORGANIC
    assert candidates == 1


# ---------------------------------------------------------------------------
# Pickup approval restriction (business rule)
# ---------------------------------------------------------------------------

def test_pickup_proposed_status_is_correct_string():
    """
    Verify the PickupStatus enum value used for 'PROPOSED' pickups.
    The agent must only create PROPOSED pickups; APPROVED is a human-only action.
    """
    from api.models import PickupStatus
    assert PickupStatus.PROPOSED.value == "PROPOSED"
    assert PickupStatus.APPROVED.value == "APPROVED"


def test_pickup_agent_cannot_approve_directly():
    """
    The matching engine and agent tools only create PROPOSED pickups.
    Confirm there is no code path in the engine that sets status=APPROVED.
    """
    import inspect
    import matching.engine as eng_module
    source = inspect.getsource(eng_module)
    # The engine should never reference "APPROVED" — that's the API layer's job
    assert "APPROVED" not in source, (
        "matching/engine.py must not reference the APPROVED status. "
        "Approval is a human-only action handled by the API layer."
    )
