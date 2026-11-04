"""
matching/engine.py
------------------
Deterministic, LLM-free matching engine for WasteLoop AI.

Design principles:
  - Pure Python: no external calls, no randomness, fully testable in isolation.
  - Hard eligibility filters are applied BEFORE scoring.  A processor that fails
    any hard filter is excluded from results entirely.
  - Scores are weighted composites; weights are defined as module-level constants
    so they can be changed in one place and re-tested.
  - The engine returns plain dataclasses so it can be called from FastAPI, tests,
    or scripts without importing any web framework.

Scoring weights (must sum to 1.0):
  WEIGHT_MATERIAL     = 0.35  (material + quality compatibility)
  WEIGHT_CAPACITY     = 0.25  (quantity fit within processor capacity)
  WEIGHT_DISTANCE     = 0.20  (proximity, capped at MAX_DISTANCE_KM)
  WEIGHT_AVAILABILITY = 0.20  (date-window overlap)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

# ---------------------------------------------------------------------------
# Weights — must sum to 1.0
# ---------------------------------------------------------------------------
WEIGHT_MATERIAL: float = 0.35
WEIGHT_CAPACITY: float = 0.25
WEIGHT_DISTANCE: float = 0.20
WEIGHT_AVAILABILITY: float = 0.20

assert abs(WEIGHT_MATERIAL + WEIGHT_CAPACITY + WEIGHT_DISTANCE + WEIGHT_AVAILABILITY - 1.0) < 1e-9, \
    "Matching weights must sum to 1.0"

# Processors beyond this distance always receive a distance score of 0.0
MAX_DISTANCE_KM: float = 50.0

# Grade ordering: A > B > C
_GRADE_ORDER: dict[str, int] = {"A": 2, "B": 1, "C": 0}


# ---------------------------------------------------------------------------
# Input / output dataclasses (no SQLAlchemy dependency)
# ---------------------------------------------------------------------------

@dataclass
class ListingInput:
    """Flat representation of a WasteListing row passed to the engine."""
    id: int
    material_type: str
    quantity_kg: float
    quality_grade: str      # "A", "B", or "C"
    available_from: date
    available_until: date
    generator_lat: float
    generator_lng: float


@dataclass
class CapacityInput:
    """Flat representation of a ProcessorCapacity row passed to the engine."""
    processor_id: int
    material_type: str
    min_quantity_kg: float
    max_quantity_kg: float
    accepted_grades: str    # comma-separated e.g. "A,B"
    available_from: date
    available_until: date
    current_load_kg: float


@dataclass
class ProcessorInput:
    """Flat representation of a Processor row passed to the engine."""
    id: int
    name: str
    processor_type: str
    lat: float
    lng: float
    is_synthetic: bool
    capacities: List[CapacityInput] = field(default_factory=list)


@dataclass
class ScoreBreakdown:
    material_score: float       # 1.0 = accepted, 0.0 = rejected (hard filter basis)
    quality_score: float        # 1.0 = exact / better, 0.5 = one tier below tolerance
    quantity_score: float       # ratio of fit within [min, max]
    distance_km: float
    distance_score: float
    availability_score: float   # fraction of listing window overlapping processor window
    composite_score: float


@dataclass
class MatchResult:
    processor_id: int
    processor_name: str
    processor_type: str
    score: float
    score_breakdown: ScoreBreakdown
    explanation: str
    is_synthetic: bool
    # The specific capacity row used for scoring (for traceability)
    matched_capacity_id: Optional[int] = None


# ---------------------------------------------------------------------------
# Haversine distance
# ---------------------------------------------------------------------------

def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return the great-circle distance in kilometres between two lat/lng points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Individual dimension scorers
# ---------------------------------------------------------------------------

def score_material(listing_material: str, capacity_material: str) -> float:
    """1.0 if materials match exactly, 0.0 otherwise (hard filter basis)."""
    return 1.0 if listing_material == capacity_material else 0.0


def score_quality(listing_grade: str, accepted_grades_csv: str) -> float:
    """
    Score quality fit.
      1.0  — listing grade is in the processor's accepted set.
      0.5  — listing grade is exactly one tier ABOVE what the processor accepts
              (processor accepts lower quality, listing is cleaner — still workable).
      0.0  — listing grade is below the minimum accepted grade (hard filter basis).
    """
    accepted = [g.strip() for g in accepted_grades_csv.split(",")]
    if listing_grade in accepted:
        return 1.0
    listing_rank = _GRADE_ORDER.get(listing_grade, -1)
    best_accepted_rank = max(_GRADE_ORDER.get(g, -1) for g in accepted)
    # Listing is cleaner than accepted — processor can handle it (minor inefficiency)
    if listing_rank > best_accepted_rank:
        return 0.5
    # Listing is dirtier than the worst grade accepted
    return 0.0


def score_quantity(
    quantity_kg: float,
    min_qty: float,
    max_qty: float,
    current_load_kg: float,
) -> float:
    """
    Score how well the listing quantity fits within available processor capacity.

    Returns 0.0 if the listing fails a hard capacity filter:
      - quantity_kg < min_qty
      - remaining headroom (max_qty - current_load_kg) < quantity_kg

    Otherwise returns a value in (0, 1] reflecting how centrally the quantity
    falls within the available window.
    """
    headroom = max_qty - current_load_kg
    if quantity_kg < min_qty:
        return 0.0
    if headroom < quantity_kg:
        return 0.0
    # Perfect fit = quantity fills the headroom exactly or is mid-range
    ratio = min(quantity_kg / headroom, headroom / max(quantity_kg, 1e-9))
    return min(ratio, 1.0)


def score_distance(distance_km: float, max_km: float = MAX_DISTANCE_KM) -> float:
    """Linear decay from 1.0 at 0 km to 0.0 at max_km. Capped at 0.0 beyond max_km."""
    return max(0.0, 1.0 - distance_km / max_km)


def score_availability(
    listing_from: date,
    listing_until: date,
    processor_from: date,
    processor_until: date,
) -> float:
    """
    Fraction of the listing's date window that overlaps the processor's available window.
    Returns 0.0 if there is no overlap (hard filter basis).
    """
    overlap_start = max(listing_from, processor_from)
    overlap_end = min(listing_until, processor_until)
    if overlap_end < overlap_start:
        return 0.0
    overlap_days = (overlap_end - overlap_start).days + 1
    listing_days = (listing_until - listing_from).days + 1
    return min(overlap_days / listing_days, 1.0)


# ---------------------------------------------------------------------------
# Hard eligibility filter
# ---------------------------------------------------------------------------

def is_eligible(
    listing: ListingInput,
    capacity: CapacityInput,
) -> tuple[bool, str]:
    """
    Apply hard eligibility filters.  Returns (True, "") if the capacity row
    is eligible, or (False, reason) if it must be excluded.

    Reasons are intentionally short and machine-readable for logging.
    """
    if capacity.material_type != listing.material_type:
        return False, "material_mismatch"

    accepted = [g.strip() for g in capacity.accepted_grades.split(",")]
    listing_rank = _GRADE_ORDER.get(listing.quality_grade, -1)
    worst_accepted_rank = min(_GRADE_ORDER.get(g, -1) for g in accepted)
    if listing_rank < worst_accepted_rank:
        return False, "grade_too_low"

    if listing.quantity_kg < capacity.min_quantity_kg:
        return False, "quantity_below_minimum"

    headroom = capacity.max_quantity_kg - capacity.current_load_kg
    if headroom < listing.quantity_kg:
        return False, "insufficient_capacity_headroom"

    if score_availability(
        listing.available_from, listing.available_until,
        capacity.available_from, capacity.available_until,
    ) == 0.0:
        return False, "no_date_overlap"

    return True, ""


# ---------------------------------------------------------------------------
# Explanation builder
# ---------------------------------------------------------------------------

def build_explanation(
    processor_name: str,
    listing: ListingInput,
    capacity: CapacityInput,
    breakdown: ScoreBreakdown,
) -> str:
    """
    Build a plain-English explanation from the score breakdown.
    This is deterministic template logic — no LLM involved.
    The agent may later rephrase this, but the factual content originates here.
    """
    parts: list[str] = []

    parts.append(
        f"{processor_name} accepts {capacity.material_type.replace('_', ' ').lower()}."
    )

    grade_desc = {1.0: "grade matches exactly", 0.5: "grade is acceptable (processor handles lower grades)"}
    parts.append(f"Quality {grade_desc.get(breakdown.quality_score, 'grade incompatible')}.")

    headroom = capacity.max_quantity_kg - capacity.current_load_kg
    parts.append(
        f"Capacity: {listing.quantity_kg:.0f} kg requested; "
        f"{headroom:.0f} kg headroom available "
        f"(min {capacity.min_quantity_kg:.0f} kg)."
    )

    parts.append(f"Distance: {breakdown.distance_km:.1f} km.")

    overlap_pct = int(breakdown.availability_score * 100)
    parts.append(f"Date window overlap: {overlap_pct}%.")

    parts.append(f"Composite score: {breakdown.composite_score:.2f} / 1.00.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------

def score_processor_for_listing(
    listing: ListingInput,
    processor: ProcessorInput,
) -> Optional[MatchResult]:
    """
    Score a single processor against a listing.

    Iterates over all capacity rows for the processor and picks the best-scoring
    eligible row.  Returns None if no eligible capacity row exists.
    """
    best: Optional[MatchResult] = None

    distance_km = haversine_km(
        listing.generator_lat, listing.generator_lng,
        processor.lat, processor.lng,
    )
    dist_score = score_distance(distance_km)

    for cap in processor.capacities:
        eligible, reason = is_eligible(listing, cap)
        if not eligible:
            continue

        mat_score  = score_material(listing.material_type, cap.material_type)
        qual_score = score_quality(listing.quality_grade, cap.accepted_grades)
        qty_score  = score_quantity(
            listing.quantity_kg,
            cap.min_quantity_kg,
            cap.max_quantity_kg,
            cap.current_load_kg,
        )
        avail_score = score_availability(
            listing.available_from, listing.available_until,
            cap.available_from, cap.available_until,
        )

        # Material score feeds into the combined material+quality dimension
        material_quality_score = (mat_score + qual_score) / 2.0

        composite = (
            WEIGHT_MATERIAL     * material_quality_score
            + WEIGHT_CAPACITY   * qty_score
            + WEIGHT_DISTANCE   * dist_score
            + WEIGHT_AVAILABILITY * avail_score
        )

        breakdown = ScoreBreakdown(
            material_score=mat_score,
            quality_score=qual_score,
            quantity_score=qty_score,
            distance_km=round(distance_km, 2),
            distance_score=round(dist_score, 4),
            availability_score=round(avail_score, 4),
            composite_score=round(composite, 4),
        )

        explanation = build_explanation(processor.name, listing, cap, breakdown)

        result = MatchResult(
            processor_id=processor.id,
            processor_name=processor.name,
            processor_type=processor.processor_type,
            score=round(composite, 4),
            score_breakdown=breakdown,
            explanation=explanation,
            is_synthetic=processor.is_synthetic,
        )

        if best is None or result.score > best.score:
            best = result

    return best


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def find_matches(
    listing: ListingInput,
    processors: List[ProcessorInput],
    top_k: int = 3,
) -> tuple[List[MatchResult], int]:
    """
    Score all processors against a listing, apply hard filters, and return
    the top-k results sorted by composite score descending.

    Returns:
        (ranked_results, total_candidates_evaluated)
        where total_candidates_evaluated counts processors that had at least
        one capacity row (eligible or not) for the listing's material type.
    """
    candidates_evaluated = 0
    results: List[MatchResult] = []

    for processor in processors:
        # Count processors that have any capacity row for this material
        has_relevant_capacity = any(
            c.material_type == listing.material_type
            for c in processor.capacities
        )
        if has_relevant_capacity:
            candidates_evaluated += 1

        result = score_processor_for_listing(listing, processor)
        if result is not None:
            results.append(result)

    # Primary sort: composite score descending
    # Tie-break: distance ascending
    results.sort(key=lambda r: (-r.score, r.score_breakdown.distance_km))

    return results[:top_k], candidates_evaluated
