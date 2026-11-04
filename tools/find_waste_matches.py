# tools/find_waste_matches.py
"""
IBM watsonx Orchestrate @tool — WasteLoop AI matching tool.

This file is SELF-CONTAINED as required by the Orchestrate ADK.
It may not import from local project modules (matching/engine.py, api/, etc.)
because the tool runs inside Orchestrate's cloud runtime, not on the local machine.

IMPORTANT — MATCHING LOGIC SYNCHRONISATION
-------------------------------------------
The matching constants, hard filters, and scoring functions below are an
INLINE COPY of matching/engine.py.  matching/engine.py is the authoritative
source.  Any change to weights, filters, or scoring in engine.py MUST be
replicated here, and vice-versa.  The drift test (tests/test_matching_drift.py)
enforces this automatically — it will fail if the two implementations diverge.

DATA FLOW (how processor data reaches this tool)
-------------------------------------------------
This tool does NOT access the local SQLite database.
Streamlit collects the listing and processor+capacity data from the local
FastAPI backend and passes them as structured JSON parameters when invoking
the Orchestrate agent.  The agent then calls this tool with that data.

  Streamlit -> GET /waste-listings/{id}           -> listing dict
  Streamlit -> GET /processors?with_capacity=true -> processors list
  Streamlit -> POST /v1/orchestrate/runs           -> agent message embedding both
  Orchestrate agent -> find_waste_matches(listing, processors, top_k)
  Tool -> returns ranked MatchOutput
  Agent -> narrates results -> returns AgentResponse to Streamlit

PICKUP APPROVAL BOUNDARY
------------------------
This tool performs READ-ONLY matching and returns recommendations.
It CANNOT create or approve pickups.  Pickup creation (PROPOSED status) and
approval (APPROVED status) are strictly Streamlit+FastAPI operations that
require explicit human action.  The ToolPermission is READ_ONLY to enforce this.
"""

import math
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission


# ---------------------------------------------------------------------------
# Matching constants — MUST stay in sync with matching/engine.py
# ---------------------------------------------------------------------------

WEIGHT_MATERIAL:     float = 0.35
WEIGHT_CAPACITY:     float = 0.25
WEIGHT_DISTANCE:     float = 0.20
WEIGHT_AVAILABILITY: float = 0.20

MAX_DISTANCE_KM: float = 50.0

_GRADE_ORDER: Dict[str, int] = {"A": 2, "B": 1, "C": 0}


# ---------------------------------------------------------------------------
# Input / Output Pydantic models
# ---------------------------------------------------------------------------

class CapacityRow(BaseModel):
    material_type:   str   = Field(description="Material type this capacity row covers")
    min_quantity_kg: float = Field(description="Minimum quantity in kg the processor accepts")
    max_quantity_kg: float = Field(description="Maximum quantity in kg the processor accepts")
    accepted_grades: str   = Field(description="Comma-separated quality grades accepted, e.g. 'A,B'")
    available_from:  str   = Field(description="ISO date string: start of availability window")
    available_until: str   = Field(description="ISO date string: end of availability window")
    current_load_kg: float = Field(description="Current committed load in kg")


class ProcessorRow(BaseModel):
    id:             int              = Field(description="Processor database ID")
    name:           str              = Field(description="Processor name")
    processor_type: str              = Field(description="Processor type, e.g. BIOGAS_PLANT")
    lat:            float            = Field(description="Latitude of processor facility")
    lng:            float            = Field(description="Longitude of processor facility")
    is_synthetic:   bool             = Field(description="True if this is demonstration data")
    capacities:     List[CapacityRow] = Field(description="All capacity rows for this processor")


class ListingRow(BaseModel):
    id:              int   = Field(description="Waste listing database ID")
    material_type:   str   = Field(description="Material type, e.g. WET_ORGANIC")
    quantity_kg:     float = Field(description="Quantity of waste available in kg")
    quality_grade:   str   = Field(description="Quality grade: A, B, or C")
    available_from:  str   = Field(description="ISO date string: earliest pickup date")
    available_until: str   = Field(description="ISO date string: latest pickup date")
    generator_lat:   float = Field(description="Latitude of the waste generator")
    generator_lng:   float = Field(description="Longitude of the waste generator")


class ScoreBreakdownOutput(BaseModel):
    material_score:     float = Field(description="1.0 if material accepted, else 0.0")
    quality_score:      float = Field(description="Quality grade fit score 0.0-1.0")
    quantity_score:     float = Field(description="Quantity fit within capacity 0.0-1.0")
    distance_km:        float = Field(description="Haversine distance in km")
    distance_score:     float = Field(description="Distance score 0.0-1.0")
    availability_score: float = Field(description="Date-window overlap fraction 0.0-1.0")
    composite_score:    float = Field(description="Weighted composite score 0.0-1.0")


class MatchOutput(BaseModel):
    processor_id:    int                  = Field(description="Processor database ID")
    processor_name:  str                  = Field(description="Processor name")
    processor_type:  str                  = Field(description="Processor type")
    score:           float                = Field(description="Composite match score 0.0-1.0")
    score_breakdown: Dict[str, Any]       = Field(description="Per-dimension score breakdown")
    explanation:     str                  = Field(description="Plain-English explanation of the match")
    is_synthetic:    bool                 = Field(description="True if demonstration data")


class MatchingResult(BaseModel):
    listing_id:              int              = Field(description="ID of the waste listing matched")
    matches:                 List[Dict[str, Any]] = Field(description="Ranked list of processor matches")
    total_candidates_evaluated: int          = Field(description="Processors that had relevant capacity")
    total_eligible:          int              = Field(description="Processors passing all hard filters")


# ---------------------------------------------------------------------------
# Inline matching logic — MUST stay in sync with matching/engine.py
# ---------------------------------------------------------------------------

def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _score_material(listing_material: str, capacity_material: str) -> float:
    return 1.0 if listing_material == capacity_material else 0.0


def _score_quality(listing_grade: str, accepted_grades_csv: str) -> float:
    accepted = [g.strip() for g in accepted_grades_csv.split(",")]
    if listing_grade in accepted:
        return 1.0
    listing_rank = _GRADE_ORDER.get(listing_grade, -1)
    best_accepted_rank = max(_GRADE_ORDER.get(g, -1) for g in accepted)
    if listing_rank > best_accepted_rank:
        return 0.5
    return 0.0


def _score_quantity(quantity_kg: float, min_qty: float, max_qty: float, current_load_kg: float) -> float:
    headroom = max_qty - current_load_kg
    if quantity_kg < min_qty:
        return 0.0
    if headroom < quantity_kg:
        return 0.0
    ratio = min(quantity_kg / headroom, headroom / max(quantity_kg, 1e-9))
    return min(ratio, 1.0)


def _score_distance(distance_km: float) -> float:
    return max(0.0, 1.0 - distance_km / MAX_DISTANCE_KM)


def _score_availability(
    listing_from: str, listing_until: str,
    processor_from: str, processor_until: str,
) -> float:
    from datetime import date
    lf = date.fromisoformat(listing_from)
    lu = date.fromisoformat(listing_until)
    pf = date.fromisoformat(processor_from)
    pu = date.fromisoformat(processor_until)
    overlap_start = max(lf, pf)
    overlap_end   = min(lu, pu)
    if overlap_end < overlap_start:
        return 0.0
    overlap_days = (overlap_end - overlap_start).days + 1
    listing_days = (lu - lf).days + 1
    return min(overlap_days / listing_days, 1.0)


def _is_eligible(listing: ListingRow, cap: CapacityRow) -> tuple:
    """Returns (True, '') if eligible, else (False, reason_string)."""
    if cap.material_type != listing.material_type:
        return False, "material_mismatch"

    accepted = [g.strip() for g in cap.accepted_grades.split(",")]
    listing_rank = _GRADE_ORDER.get(listing.quality_grade, -1)
    worst_accepted_rank = min(_GRADE_ORDER.get(g, -1) for g in accepted)
    if listing_rank < worst_accepted_rank:
        return False, "grade_too_low"

    if listing.quantity_kg < cap.min_quantity_kg:
        return False, "quantity_below_minimum"

    headroom = cap.max_quantity_kg - cap.current_load_kg
    if headroom < listing.quantity_kg:
        return False, "insufficient_capacity_headroom"

    if _score_availability(
        listing.available_from, listing.available_until,
        cap.available_from, cap.available_until,
    ) == 0.0:
        return False, "no_date_overlap"

    return True, ""


def _build_explanation(
    processor_name: str,
    listing: ListingRow,
    cap: CapacityRow,
    breakdown: dict,
) -> str:
    parts = []
    parts.append(f"{processor_name} accepts {cap.material_type.replace('_', ' ').lower()}.")
    grade_desc = {1.0: "grade matches exactly", 0.5: "grade is acceptable (processor handles lower grades)"}
    parts.append(f"Quality {grade_desc.get(breakdown['quality_score'], 'grade incompatible')}.")
    headroom = cap.max_quantity_kg - cap.current_load_kg
    parts.append(
        f"Capacity: {listing.quantity_kg:.0f} kg requested; "
        f"{headroom:.0f} kg headroom available "
        f"(min {cap.min_quantity_kg:.0f} kg)."
    )
    parts.append(f"Distance: {breakdown['distance_km']:.1f} km.")
    overlap_pct = int(breakdown["availability_score"] * 100)
    parts.append(f"Date window overlap: {overlap_pct}%.")
    parts.append(f"Composite score: {breakdown['composite_score']:.2f} / 1.00.")
    return " ".join(parts)


def _score_processor(listing: ListingRow, processor: ProcessorRow) -> Optional[Dict[str, Any]]:
    """Score one processor against a listing. Returns None if no eligible capacity."""
    distance_km = _haversine_km(
        listing.generator_lat, listing.generator_lng,
        processor.lat, processor.lng,
    )
    dist_score = _score_distance(distance_km)

    best: Optional[Dict[str, Any]] = None

    for cap in processor.capacities:
        eligible, _ = _is_eligible(listing, cap)
        if not eligible:
            continue

        mat_score  = _score_material(listing.material_type, cap.material_type)
        qual_score = _score_quality(listing.quality_grade, cap.accepted_grades)
        qty_score  = _score_quantity(
            listing.quantity_kg,
            cap.min_quantity_kg, cap.max_quantity_kg, cap.current_load_kg,
        )
        avail_score = _score_availability(
            listing.available_from, listing.available_until,
            cap.available_from, cap.available_until,
        )

        material_quality_score = (mat_score + qual_score) / 2.0

        composite = (
            WEIGHT_MATERIAL      * material_quality_score
            + WEIGHT_CAPACITY    * qty_score
            + WEIGHT_DISTANCE    * dist_score
            + WEIGHT_AVAILABILITY * avail_score
        )

        breakdown = {
            "material_score":     mat_score,
            "quality_score":      qual_score,
            "quantity_score":     round(qty_score, 4),
            "distance_km":        round(distance_km, 2),
            "distance_score":     round(dist_score, 4),
            "availability_score": round(avail_score, 4),
            "composite_score":    round(composite, 4),
        }

        explanation = _build_explanation(processor.name, listing, cap, breakdown)

        candidate = {
            "processor_id":    processor.id,
            "processor_name":  processor.name,
            "processor_type":  processor.processor_type,
            "score":           round(composite, 4),
            "score_breakdown": breakdown,
            "explanation":     explanation,
            "is_synthetic":    processor.is_synthetic,
        }

        if best is None or candidate["score"] > best["score"]:
            best = candidate

    return best


# ---------------------------------------------------------------------------
# @tool entry point
# ---------------------------------------------------------------------------

@tool(permission=ToolPermission.READ_ONLY)
def find_waste_matches(
    listing: ListingRow,
    processors: List[ProcessorRow],
    top_k: int = 3,
) -> MatchingResult:
    """
    Find and rank waste processors that can handle a specific waste listing.

    Applies hard eligibility filters (material type, quantity, quality grade,
    capacity headroom, date-window overlap) and then scores eligible processors
    on a weighted composite: material+quality compatibility (35%), capacity fit
    (25%), distance (20%), and availability (20%).

    This tool performs READ-ONLY matching. It does not create or approve pickups.
    Pickup creation and approval are separate human-authorised actions in the
    Streamlit interface.

    Note: all data marked is_synthetic=True is demonstration data.

    Args:
        listing (ListingRow): The waste listing to match against processors.
        processors (List[ProcessorRow]): Candidate processors with their capacity data.
        top_k (int): Maximum number of top-ranked results to return (default 3).
    Returns:
        MatchingResult: Ranked list of matching processors with scores and explanations.
    """
    results = []
    candidates_evaluated = 0

    for processor in processors:
        has_relevant = any(
            c.material_type == listing.material_type
            for c in processor.capacities
        )
        if has_relevant:
            candidates_evaluated += 1

        match = _score_processor(listing, processor)
        if match is not None:
            results.append(match)

    # Sort: composite score descending, tie-break by distance ascending
    results.sort(key=lambda r: (-r["score"], r["score_breakdown"]["distance_km"]))
    top_results = results[:top_k]

    return MatchingResult(
        listing_id=listing.id,
        matches=top_results,
        total_candidates_evaluated=candidates_evaluated,
        total_eligible=len(results),
    )
