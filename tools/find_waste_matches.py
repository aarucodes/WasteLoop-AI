# tools/find_waste_matches.py
"""
IBM watsonx Orchestrate @tool -- WasteLoop AI matching tool.

DESIGN: flat scalar inputs only (no nested lists/objects).
The tool carries an EMBEDDED SYNTHETIC PROCESSOR SNAPSHOT generated from
data/processors.csv and data/processor_capacity.csv.

IMPORTANT -- MATCHING LOGIC SYNCHRONISATION
All matching constants and scoring functions below are an INLINE COPY of
matching/engine.py.  matching/engine.py is the AUTHORITATIVE source.
The drift test (tests/test_matching_drift.py) enforces parity automatically.

DATA NOTE: all processor data in this snapshot is SYNTHETIC DEMONSTRATION DATA.
It does NOT represent live processor availability.  Every result includes the
snapshot_id so the backend can verify results against the same snapshot version.

PICKUP APPROVAL BOUNDARY
This tool is READ_ONLY.  It cannot create or approve pickups.
ToolPermission.READ_ONLY enforces this at the platform level.
"""

import math
from datetime import date
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission

# ---------------------------------------------------------------------------
# Matching constants -- MUST stay in sync with matching/engine.py
# ---------------------------------------------------------------------------
WEIGHT_MATERIAL:     float = 0.35
WEIGHT_CAPACITY:     float = 0.25
WEIGHT_DISTANCE:     float = 0.20
WEIGHT_AVAILABILITY: float = 0.20
MAX_DISTANCE_KM:     float = 50.0
_GRADE_ORDER: Dict[str, int] = {"A": 2, "B": 1, "C": 0}

# ---------------------------------------------------------------------------
# Embedded synthetic processor snapshot
# Generated from: data/processors.csv + data/processor_capacity.csv
# Snapshot ID changes when CSVs change (update SNAPSHOT_ID and _SNAPSHOT).
# ---------------------------------------------------------------------------
SNAPSHOT_ID = "wasteloop-snapshot-v1-20261104"

_SNAPSHOT: List[Dict[str, Any]] = [
    {"id": 1,  "name": "GreenBio Bengaluru",      "type": "BIOGAS_PLANT",
     "lat": 13.0289, "lng": 77.5192, "synthetic": True,
     "caps": [{"mat": "WET_ORGANIC", "min": 100, "max": 2000, "grades": "A",
               "from": "2026-11-01", "until": "2026-11-30", "load": 400}]},
    {"id": 2,  "name": "Bengaluru Biogas Works",   "type": "BIOGAS_PLANT",
     "lat": 13.0982, "lng": 77.3912, "synthetic": True,
     "caps": [{"mat": "WET_ORGANIC", "min": 200, "max": 5000, "grades": "A",
               "from": "2026-11-01", "until": "2026-11-30", "load": 1000},
              {"mat": "WET_ORGANIC", "min": 200, "max": 5000, "grades": "B",
               "from": "2026-11-05", "until": "2026-11-30", "load": 0}]},
    {"id": 3,  "name": "EcoCompost Yelahanka",     "type": "COMPOST_FACILITY",
     "lat": 13.0998, "lng": 77.5963, "synthetic": True,
     "caps": [{"mat": "WET_ORGANIC", "min": 50, "max": 1000, "grades": "A",
               "from": "2026-11-01", "until": "2026-11-30", "load": 200},
              {"mat": "WET_ORGANIC", "min": 50, "max": 1000, "grades": "B",
               "from": "2026-11-01", "until": "2026-11-30", "load": 100}]},
    {"id": 4,  "name": "PaperFirst Recyclers",     "type": "PAPER_RECYCLER",
     "lat": 12.8253, "lng": 77.6981, "synthetic": True,
     "caps": [{"mat": "DRY_PAPER", "min": 100, "max": 3000, "grades": "A",
               "from": "2026-11-01", "until": "2026-11-30", "load": 500},
              {"mat": "DRY_PAPER", "min": 100, "max": 3000, "grades": "B",
               "from": "2026-11-01", "until": "2026-11-30", "load": 200}]},
    {"id": 5,  "name": "CleanSheet Paper",         "type": "PAPER_RECYCLER",
     "lat": 13.1019, "lng": 77.3762, "synthetic": True,
     "caps": [{"mat": "DRY_PAPER", "min": 200, "max": 5000, "grades": "A",
               "from": "2026-11-01", "until": "2026-11-30", "load": 800},
              {"mat": "DRY_PAPER", "min": 200, "max": 5000, "grades": "B",
               "from": "2026-11-01", "until": "2026-11-30", "load": 300}]},
    {"id": 6,  "name": "PlastiLoop Recyclers",     "type": "PLASTIC_RECYCLER",
     "lat": 12.9826, "lng": 77.7396, "synthetic": True,
     "caps": [{"mat": "DRY_PLASTIC", "min": 50, "max": 2000, "grades": "A",
               "from": "2026-11-01", "until": "2026-11-30", "load": 300},
              {"mat": "DRY_PLASTIC", "min": 50, "max": 2000, "grades": "B",
               "from": "2026-11-01", "until": "2026-11-30", "load": 150}]},
    {"id": 7,  "name": "GreenMetal Scrap",         "type": "METAL_RECYCLER",
     "lat": 13.0254, "lng": 77.5098, "synthetic": True,
     "caps": [{"mat": "DRY_METAL", "min": 100, "max": 4000, "grades": "A",
               "from": "2026-11-01", "until": "2026-11-30", "load": 600},
              {"mat": "DRY_METAL", "min": 100, "max": 4000, "grades": "B",
               "from": "2026-11-01", "until": "2026-11-30", "load": 200}]},
    {"id": 8,  "name": "E-Cycle Hub",              "type": "E_WASTE_HANDLER",
     "lat": 12.8394, "lng": 77.6681, "synthetic": True,
     "caps": [{"mat": "E_WASTE", "min": 10, "max": 500, "grades": "A",
               "from": "2026-11-01", "until": "2026-11-30", "load": 50},
              {"mat": "E_WASTE", "min": 10, "max": 500, "grades": "B",
               "from": "2026-11-01", "until": "2026-11-30", "load": 20}]},
    {"id": 9,  "name": "GlassBack Recyclers",      "type": "GLASS_RECYCLER",
     "lat": 12.9026, "lng": 77.6273, "synthetic": True,
     "caps": [{"mat": "GLASS", "min": 50, "max": 1500, "grades": "A",
               "from": "2026-11-01", "until": "2026-11-30", "load": 100},
              {"mat": "GLASS", "min": 50, "max": 1500, "grades": "B",
               "from": "2026-11-01", "until": "2026-11-30", "load": 50}]},
    {"id": 10, "name": "Hasiru Dala Innovations",  "type": "COMPOST_FACILITY",
     "lat": 12.9073, "lng": 77.4887, "synthetic": True,
     "caps": [{"mat": "WET_ORGANIC", "min": 50, "max": 800, "grades": "A",
               "from": "2026-11-01", "until": "2026-11-30", "load": 150},
              {"mat": "WET_ORGANIC", "min": 50, "max": 800, "grades": "B",
               "from": "2026-11-01", "until": "2026-11-30", "load": 80},
              {"mat": "WET_ORGANIC", "min": 50, "max": 800, "grades": "C",
               "from": "2026-11-01", "until": "2026-11-30", "load": 0}]},
]

# ---------------------------------------------------------------------------
# Inline matching logic -- MUST stay in sync with matching/engine.py
# ---------------------------------------------------------------------------

def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _score_material(lm: str, cm: str) -> float:
    return 1.0 if lm == cm else 0.0


def _score_quality(listing_grade: str, accepted_grades_csv: str) -> float:
    accepted = [g.strip() for g in accepted_grades_csv.split(",")]
    if listing_grade in accepted:
        return 1.0
    lr = _GRADE_ORDER.get(listing_grade, -1)
    br = max(_GRADE_ORDER.get(g, -1) for g in accepted)
    return 0.5 if lr > br else 0.0


def _score_quantity(qty: float, mn: float, mx: float, load: float) -> float:
    headroom = mx - load
    if qty < mn or headroom < qty:
        return 0.0
    ratio = min(qty / headroom, headroom / max(qty, 1e-9))
    return min(ratio, 1.0)


def _score_distance(d: float) -> float:
    return max(0.0, 1.0 - d / MAX_DISTANCE_KM)


def _score_availability(lf: str, lu: str, pf: str, pu: str) -> float:
    a = date.fromisoformat(lf); b = date.fromisoformat(lu)
    c = date.fromisoformat(pf); d = date.fromisoformat(pu)
    os_ = max(a, c); oe = min(b, d)
    if oe < os_:
        return 0.0
    return min((oe - os_).days + 1, 1) / max((b - a).days + 1, 1) * \
           ((oe - os_).days + 1) / max((oe - os_).days + 1, 1)


def _avail_score(lf: str, lu: str, pf: str, pu: str) -> float:
    a = date.fromisoformat(lf); b = date.fromisoformat(lu)
    c = date.fromisoformat(pf); d = date.fromisoformat(pu)
    os_ = max(a, c); oe = min(b, d)
    if oe < os_:
        return 0.0
    overlap = (oe - os_).days + 1
    listing_days = (b - a).days + 1
    return min(overlap / listing_days, 1.0)


def _is_eligible(material: str, quantity: float, grade: str,
                 avail_from: str, avail_until: str, cap: dict) -> tuple:
    if cap["mat"] != material:
        return False, "material_mismatch"
    accepted = [g.strip() for g in cap["grades"].split(",")]
    lr = _GRADE_ORDER.get(grade, -1)
    wr = min(_GRADE_ORDER.get(g, -1) for g in accepted)
    if lr < wr:
        return False, "grade_too_low"
    if quantity < cap["min"]:
        return False, "quantity_below_minimum"
    if cap["max"] - cap["load"] < quantity:
        return False, "insufficient_capacity_headroom"
    if _avail_score(avail_from, avail_until, cap["from"], cap["until"]) == 0.0:
        return False, "no_date_overlap"
    return True, ""


def _score_processor(material: str, quantity: float, grade: str,
                     avail_from: str, avail_until: str,
                     gen_lat: float, gen_lng: float,
                     proc: dict) -> Optional[dict]:
    dist = _haversine_km(gen_lat, gen_lng, proc["lat"], proc["lng"])
    dist_s = _score_distance(dist)
    best = None
    for cap in proc["caps"]:
        ok, _ = _is_eligible(material, quantity, grade, avail_from, avail_until, cap)
        if not ok:
            continue
        mat_s  = _score_material(material, cap["mat"])
        qual_s = _score_quality(grade, cap["grades"])
        qty_s  = _score_quantity(quantity, cap["min"], cap["max"], cap["load"])
        avs    = _avail_score(avail_from, avail_until, cap["from"], cap["until"])
        mq     = (mat_s + qual_s) / 2.0
        comp   = (WEIGHT_MATERIAL * mq + WEIGHT_CAPACITY * qty_s
                  + WEIGHT_DISTANCE * dist_s + WEIGHT_AVAILABILITY * avs)
        headroom = cap["max"] - cap["load"]
        expl = (
            f"{proc['name']} accepts {cap['mat'].replace('_',' ').lower()}. "
            f"Quality {'matches exactly' if qual_s == 1.0 else 'acceptable'}. "
            f"Capacity: {quantity:.0f} kg requested; {headroom:.0f} kg headroom "
            f"(min {cap['min']:.0f} kg). "
            f"Distance: {dist:.1f} km. "
            f"Date window overlap: {int(avs*100)}%. "
            f"Composite score: {comp:.2f}/1.00."
        )
        candidate = {
            "processor_id":   proc["id"],
            "processor_name": proc["name"],
            "processor_type": proc["type"],
            "score":          round(comp, 4),
            "score_breakdown": {
                "material_score":     mat_s,
                "quality_score":      qual_s,
                "quantity_score":     round(qty_s, 4),
                "distance_km":        round(dist, 2),
                "distance_score":     round(dist_s, 4),
                "availability_score": round(avs, 4),
                "composite_score":    round(comp, 4),
            },
            "explanation": expl,
            "is_synthetic": proc["synthetic"],
        }
        if best is None or candidate["score"] > best["score"]:
            best = candidate
    return best


# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------

class MatchResult(BaseModel):
    snapshot_id:             str   = Field(description="Snapshot ID for backend verification")
    processor_count:         int   = Field(description="Number of processors in snapshot")
    listing_id:              int   = Field(description="Listing ID passed to the tool")
    material_type:           str   = Field(description="Material type matched against")
    total_candidates:        int   = Field(description="Processors with relevant capacity")
    total_eligible:          int   = Field(description="Processors passing all hard filters")
    top_matches:             str   = Field(description="JSON string of ranked matches (list)")
    recommended_processor_id: int  = Field(description="ID of top-ranked processor, -1 if none")
    proposed_pickup_date:    str   = Field(description="Suggested pickup date (ISO) within window, or empty")
    scoring_formula:         str   = Field(description="Exact scoring formula; material and quality are averaged inside one 35 percent dimension")
    note:                    str   = Field(description="Human-readable summary for agent narration")


# ---------------------------------------------------------------------------
# @tool entry point -- flat scalar inputs only
# ---------------------------------------------------------------------------

@tool(permission=ToolPermission.READ_ONLY)
def find_waste_matches(
    listing_id:     int,
    material_type:  str,
    quantity_kg:    float,
    quality_grade:  str,
    available_from: str,
    available_until: str,
    generator_lat:  float,
    generator_lng:  float,
    top_k:          int = 3,
) -> MatchResult:
    """
    Find and rank waste processors for a waste listing using the embedded synthetic snapshot.

    Uses hard eligibility filters (material, quantity, grade, capacity, dates) then
    scores eligible processors on: material+quality 35%, capacity 25%, distance 20%,
    availability 20%. All processor data is SYNTHETIC DEMONSTRATION DATA (snapshot_id
    identifies the snapshot version). This tool is READ-ONLY and cannot create or approve
    pickups.

    Args:
        listing_id (int): Database ID of the waste listing.
        material_type (str): Material type e.g. WET_ORGANIC, DRY_PAPER, DRY_PLASTIC, DRY_METAL, E_WASTE, GLASS.
        quantity_kg (float): Quantity of waste available in kg.
        quality_grade (str): Quality grade A (clean), B (minor contamination), or C (mixed).
        available_from (str): Earliest pickup date ISO format YYYY-MM-DD.
        available_until (str): Latest pickup date ISO format YYYY-MM-DD.
        generator_lat (float): Latitude of waste generator.
        generator_lng (float): Longitude of waste generator.
        top_k (int): Maximum ranked results to return, default 3.
    Returns:
        MatchResult: Ranked matches with scores, snapshot_id, and proposed pickup date.
    """
    import json as _json

    results = []
    candidates = 0
    for proc in _SNAPSHOT:
        has_rel = any(c["mat"] == material_type for c in proc["caps"])
        if has_rel:
            candidates += 1
        m = _score_processor(material_type, quantity_kg, quality_grade,
                             available_from, available_until,
                             generator_lat, generator_lng, proc)
        if m is not None:
            results.append(m)

    results.sort(key=lambda r: (-r["score"], r["score_breakdown"]["distance_km"]))
    top = results[:top_k]

    # Propose pickup date: midpoint of available window, clamped to today+
    proposed_date = ""
    if top:
        try:
            af = date.fromisoformat(available_from)
            au = date.fromisoformat(available_until)
            today = date.today()
            start = max(af, today)
            if start <= au:
                mid = start + (au - start) // 2
                proposed_date = mid.isoformat()
        except Exception:
            pass

    rec_id = top[0]["processor_id"] if top else -1
    note = (
        f"Found {len(top)} eligible processor(s) from synthetic snapshot {SNAPSHOT_ID}. "
        + (f"Top recommendation: {top[0]['processor_name']} (score {top[0]['score']:.2f}). "
           f"Proposed pickup: {proposed_date}. "
           f"This is a proposal only -- human approval required."
           if top else "No processors passed eligibility filters.")
    )

    return MatchResult(
        snapshot_id=SNAPSHOT_ID,
        processor_count=len(_SNAPSHOT),
        listing_id=listing_id,
        material_type=material_type,
        total_candidates=candidates,
        total_eligible=len(results),
        top_matches=_json.dumps(top),
        recommended_processor_id=rec_id,
        proposed_pickup_date=proposed_date,
        scoring_formula=(
            "composite = 0.35 * ((material_score + quality_score) / 2) "
            "+ 0.25 * quantity_score + 0.20 * distance_score "
            "+ 0.20 * availability_score. Material and quality are sub-scores "
            "inside one combined 35% dimension; the four weights total 100%."
        ),
        note=note,
    )
