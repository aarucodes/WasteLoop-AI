"""
tests/test_matching_drift.py
----------------------------
Drift test: asserts that the inline matching logic embedded in
tools/find_waste_matches.py produces IDENTICAL results to the
authoritative implementation in matching/engine.py.

If EITHER implementation changes independently this test will fail,
preventing silent algorithm divergence between the cloud tool and the
local backend.

Test structure
--------------
  SHARED_FIXTURES  – plain dicts (JSON-serialisable), used by both sides.
  _run_engine()    – feeds fixtures into matching/engine.py dataclasses.
  _run_tool()      – feeds fixtures into the tool's Pydantic models.
  Assertions       – eligible set, composite scores, breakdown fields,
                     ranking order, rejection reasons.
"""

import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Import the authoritative engine ──────────────────────────────────────────
from matching.engine import (
    CapacityInput,
    ListingInput,
    ProcessorInput,
    find_matches as engine_find_matches,
    is_eligible as engine_is_eligible,
    score_availability,
    score_distance,
    score_material,
    score_quality,
    score_quantity,
    haversine_km,
)

# ── Import the tool module ────────────────────────────────────────────────────
# The tool file is self-contained; import it directly.
import importlib.util, types

_TOOL_PATH = ROOT / "tools" / "find_waste_matches.py"

def _load_tool_module() -> types.ModuleType:
    """Load tools/find_waste_matches.py without executing the @tool decorator
    side-effects at import time (the decorator is harmless but we want isolation)."""
    spec = importlib.util.spec_from_file_location("find_waste_matches", _TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_tool_mod = _load_tool_module()

# ── Shared fixtures (plain JSON-serialisable dicts) ───────────────────────────
#
# Covers:
#   F1  – perfect match (all hard filters pass, high score)
#   F2  – material mismatch (hard filter: excluded)
#   F3  – quantity below minimum (hard filter: excluded)
#   F4  – insufficient headroom (hard filter: excluded)
#   F5  – no date overlap (hard filter: excluded)
#   F6  – grade too dirty (hard filter: excluded)
#   F7  – partial date overlap (scoring, not excluded)
#   F8  – distant processor (low distance score but eligible)
#   F9  – tie-break scenario (same scores, different distances)

LISTING_WET_A: Dict[str, Any] = {
    "id": 1,
    "material_type": "WET_ORGANIC",
    "quantity_kg": 300.0,
    "quality_grade": "A",
    "available_from": "2026-11-05",
    "available_until": "2026-11-12",
    "generator_lat": 12.9716,
    "generator_lng": 77.5946,
}

LISTING_DRY_PAPER_B: Dict[str, Any] = {
    "id": 2,
    "material_type": "DRY_PAPER",
    "quantity_kg": 200.0,
    "quality_grade": "B",
    "available_from": "2026-11-07",
    "available_until": "2026-11-14",
    "generator_lat": 12.9716,
    "generator_lng": 77.5946,
}

# Processor fixtures
def _make_proc(
    pid: int,
    name: str,
    ptype: str,
    lat: float,
    lng: float,
    capacities: List[Dict],
) -> Dict[str, Any]:
    return {
        "id": pid,
        "name": name,
        "processor_type": ptype,
        "lat": lat,
        "lng": lng,
        "is_synthetic": True,
        "capacities": capacities,
    }

def _cap(
    material: str = "WET_ORGANIC",
    min_qty: float = 100.0,
    max_qty: float = 2000.0,
    grades: str = "A",
    avail_from: str = "2026-11-01",
    avail_until: str = "2026-11-30",
    load: float = 0.0,
) -> Dict[str, Any]:
    return {
        "material_type": material,
        "min_quantity_kg": min_qty,
        "max_quantity_kg": max_qty,
        "accepted_grades": grades,
        "available_from": avail_from,
        "available_until": avail_until,
        "current_load_kg": load,
    }

# F1: perfect eligible match
PROC_F1 = _make_proc(1, "Good Biogas", "BIOGAS_PLANT", 12.9716, 77.5946, [_cap()])

# F2: wrong material
PROC_F2 = _make_proc(2, "Paper Only", "PAPER_RECYCLER", 12.97, 77.59, [_cap(material="DRY_PAPER")])

# F3: quantity below minimum
PROC_F3 = _make_proc(3, "Large Biogas", "BIOGAS_PLANT", 12.97, 77.59, [_cap(min_qty=500.0)])

# F4: insufficient headroom
PROC_F4 = _make_proc(4, "Full Biogas", "BIOGAS_PLANT", 12.97, 77.59, [_cap(max_qty=1000.0, load=750.0)])

# F5: no date overlap
PROC_F5 = _make_proc(5, "Future Biogas", "BIOGAS_PLANT", 12.97, 77.59, [
    _cap(avail_from="2026-11-20", avail_until="2026-11-30")
])

# F6: grade too dirty (processor only takes A, listing is C)
PROC_F6 = _make_proc(6, "Grade A Only", "BIOGAS_PLANT", 12.97, 77.59, [_cap(grades="A")])
LISTING_WET_C = {**LISTING_WET_A, "id": 99, "quality_grade": "C"}

# F7: partial date overlap — eligible but lower availability score
PROC_F7 = _make_proc(7, "Partial Window", "BIOGAS_PLANT", 12.97, 77.59, [
    _cap(avail_from="2026-11-09", avail_until="2026-11-30")  # overlap: Nov 9-12 = 4/8 days
])

# F8: distant processor (~40 km away)
PROC_F8 = _make_proc(8, "Distant Biogas", "BIOGAS_PLANT", 13.33, 77.59, [_cap()])

# F9a and F9b: identical eligibility but different distances (for tie-break test)
PROC_F9A = _make_proc(9,  "Close Biogas", "BIOGAS_PLANT", 12.9716 + 0.018, 77.5946, [_cap()])   # ~2 km
PROC_F9B = _make_proc(10, "Mid Biogas",   "BIOGAS_PLANT", 12.9716 + 0.090, 77.5946, [_cap()])   # ~10 km

ALL_PROCESSORS = [PROC_F1, PROC_F2, PROC_F3, PROC_F4, PROC_F5, PROC_F7, PROC_F8, PROC_F9A, PROC_F9B]


# ── Adapter: shared dict → engine dataclasses ─────────────────────────────────

def _dict_to_listing_input(d: Dict) -> ListingInput:
    return ListingInput(
        id=d["id"],
        material_type=d["material_type"],
        quantity_kg=d["quantity_kg"],
        quality_grade=d["quality_grade"],
        available_from=date.fromisoformat(d["available_from"]),
        available_until=date.fromisoformat(d["available_until"]),
        generator_lat=d["generator_lat"],
        generator_lng=d["generator_lng"],
    )

def _dict_to_processor_input(d: Dict) -> ProcessorInput:
    caps = [
        CapacityInput(
            processor_id=d["id"],
            material_type=c["material_type"],
            min_quantity_kg=c["min_quantity_kg"],
            max_quantity_kg=c["max_quantity_kg"],
            accepted_grades=c["accepted_grades"],
            available_from=date.fromisoformat(c["available_from"]),
            available_until=date.fromisoformat(c["available_until"]),
            current_load_kg=c["current_load_kg"],
        )
        for c in d["capacities"]
    ]
    return ProcessorInput(
        id=d["id"],
        name=d["name"],
        processor_type=d["processor_type"],
        lat=d["lat"],
        lng=d["lng"],
        is_synthetic=d["is_synthetic"],
        capacities=caps,
    )


# ── Adapter: shared dict → tool Pydantic models ───────────────────────────────

def _dict_to_tool_listing(d: Dict):
    ListingRow = _tool_mod.ListingRow
    return ListingRow(**d)

def _dict_to_tool_processor(d: Dict):
    ProcessorRow = _tool_mod.ProcessorRow
    CapacityRow  = _tool_mod.CapacityRow
    caps = [CapacityRow(**c) for c in d["capacities"]]
    return ProcessorRow(
        id=d["id"], name=d["name"], processor_type=d["processor_type"],
        lat=d["lat"], lng=d["lng"], is_synthetic=d["is_synthetic"],
        capacities=caps,
    )


# ── Runner helpers ─────────────────────────────────────────────────────────────

def _run_engine(listing_dict: Dict, proc_dicts: List[Dict], top_k: int = 5):
    listing = _dict_to_listing_input(listing_dict)
    processors = [_dict_to_processor_input(p) for p in proc_dicts]
    results, candidates = engine_find_matches(listing, processors, top_k=top_k)
    return results, candidates

def _run_tool(listing_dict: Dict, proc_dicts: List[Dict], top_k: int = 5) -> dict:
    listing  = _dict_to_tool_listing(listing_dict)
    procs    = [_dict_to_tool_processor(p) for p in proc_dicts]
    # Call the tool function directly (unwrapped from @tool decorator)
    result   = _tool_mod.find_waste_matches.fn(listing=listing, processors=procs, top_k=top_k)
    # The tool returns a MatchingResult Pydantic model; normalise to dict for assertions
    if hasattr(result, "model_dump"):
        return result.model_dump()
    return result


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestEligibleSet:
    """Both implementations must agree on which processors pass hard filters."""

    def test_perfect_match_both_eligible(self):
        eng_results, _ = _run_engine(LISTING_WET_A, [PROC_F1])
        tool_result     = _run_tool(LISTING_WET_A,  [PROC_F1])
        assert len(eng_results) == 1,                 "engine: F1 should be eligible"
        assert tool_result["total_eligible"] == 1,    "tool: F1 should be eligible"

    def test_material_mismatch_both_reject(self):
        eng_results, _ = _run_engine(LISTING_WET_A, [PROC_F2])
        tool_result     = _run_tool(LISTING_WET_A,  [PROC_F2])
        assert len(eng_results) == 0,                  "engine: F2 should be rejected"
        assert tool_result["total_eligible"] == 0,     "tool: F2 should be rejected"

    def test_quantity_below_minimum_both_reject(self):
        eng_results, _ = _run_engine(LISTING_WET_A, [PROC_F3])
        tool_result     = _run_tool(LISTING_WET_A,  [PROC_F3])
        assert len(eng_results) == 0
        assert tool_result["total_eligible"] == 0

    def test_insufficient_headroom_both_reject(self):
        eng_results, _ = _run_engine(LISTING_WET_A, [PROC_F4])
        tool_result     = _run_tool(LISTING_WET_A,  [PROC_F4])
        assert len(eng_results) == 0
        assert tool_result["total_eligible"] == 0

    def test_no_date_overlap_both_reject(self):
        eng_results, _ = _run_engine(LISTING_WET_A, [PROC_F5])
        tool_result     = _run_tool(LISTING_WET_A,  [PROC_F5])
        assert len(eng_results) == 0
        assert tool_result["total_eligible"] == 0

    def test_grade_too_dirty_both_reject(self):
        eng_results, _ = _run_engine(LISTING_WET_C, [PROC_F6])
        tool_result     = _run_tool(LISTING_WET_C,  [PROC_F6])
        assert len(eng_results) == 0
        assert tool_result["total_eligible"] == 0


class TestScoreMatch:
    """Both implementations must produce identical composite scores and breakdowns."""

    SCORE_TOL = 1e-6  # floating-point tolerance

    def _engine_score(self, listing_d, proc_d):
        results, _ = _run_engine(listing_d, [proc_d], top_k=1)
        assert results, f"engine returned no results for proc {proc_d['id']}"
        return results[0]

    def _tool_score(self, listing_d, proc_d):
        result = _run_tool(listing_d, [proc_d], top_k=1)
        assert result["matches"], f"tool returned no matches for proc {proc_d['id']}"
        return result["matches"][0]

    def test_composite_score_identical_f1(self):
        e = self._engine_score(LISTING_WET_A, PROC_F1)
        t = self._tool_score(LISTING_WET_A,   PROC_F1)
        assert abs(e.score - t["score"]) < self.SCORE_TOL, (
            f"engine score {e.score} != tool score {t['score']}"
        )

    def test_composite_score_identical_f7(self):
        """Partial availability — scores must agree."""
        e = self._engine_score(LISTING_WET_A, PROC_F7)
        t = self._tool_score(LISTING_WET_A,   PROC_F7)
        assert abs(e.score - t["score"]) < self.SCORE_TOL

    def test_composite_score_identical_f8(self):
        """Distant processor — distance score must agree."""
        e = self._engine_score(LISTING_WET_A, PROC_F8)
        t = self._tool_score(LISTING_WET_A,   PROC_F8)
        assert abs(e.score - t["score"]) < self.SCORE_TOL

    def test_score_breakdown_material(self):
        e = self._engine_score(LISTING_WET_A, PROC_F1)
        t = self._tool_score(LISTING_WET_A,   PROC_F1)
        assert abs(e.score_breakdown.material_score - t["score_breakdown"]["material_score"]) < self.SCORE_TOL

    def test_score_breakdown_quality(self):
        e = self._engine_score(LISTING_WET_A, PROC_F1)
        t = self._tool_score(LISTING_WET_A,   PROC_F1)
        assert abs(e.score_breakdown.quality_score - t["score_breakdown"]["quality_score"]) < self.SCORE_TOL

    def test_score_breakdown_quantity(self):
        e = self._engine_score(LISTING_WET_A, PROC_F1)
        t = self._tool_score(LISTING_WET_A,   PROC_F1)
        assert abs(e.score_breakdown.quantity_score - t["score_breakdown"]["quantity_score"]) < self.SCORE_TOL

    def test_score_breakdown_distance_km(self):
        e = self._engine_score(LISTING_WET_A, PROC_F8)
        t = self._tool_score(LISTING_WET_A,   PROC_F8)
        assert abs(e.score_breakdown.distance_km - t["score_breakdown"]["distance_km"]) < 0.01

    def test_score_breakdown_availability(self):
        """Partial overlap — availability score must match."""
        e = self._engine_score(LISTING_WET_A, PROC_F7)
        t = self._tool_score(LISTING_WET_A,   PROC_F7)
        assert abs(e.score_breakdown.availability_score - t["score_breakdown"]["availability_score"]) < self.SCORE_TOL

    def test_score_breakdown_composite_matches_top_level(self):
        """score_breakdown.composite_score must equal the top-level score field."""
        t = self._tool_score(LISTING_WET_A, PROC_F1)
        assert abs(t["score"] - t["score_breakdown"]["composite_score"]) < self.SCORE_TOL


class TestRankingOrder:
    """Both implementations must produce the same ranking order."""

    def test_ranking_order_matches(self):
        eng_results, _ = _run_engine(LISTING_WET_A, ALL_PROCESSORS, top_k=9)
        tool_result     = _run_tool(LISTING_WET_A,  ALL_PROCESSORS, top_k=9)

        eng_ids  = [r.processor_id for r in eng_results]
        tool_ids = [m["processor_id"] for m in tool_result["matches"]]
        assert eng_ids == tool_ids, (
            f"Ranking order differs:\n  engine: {eng_ids}\n  tool:   {tool_ids}"
        )

    def test_scores_descending_engine(self):
        eng_results, _ = _run_engine(LISTING_WET_A, ALL_PROCESSORS, top_k=9)
        scores = [r.score for r in eng_results]
        assert scores == sorted(scores, reverse=True)

    def test_scores_descending_tool(self):
        tool_result = _run_tool(LISTING_WET_A, ALL_PROCESSORS, top_k=9)
        scores = [m["score"] for m in tool_result["matches"]]
        assert scores == sorted(scores, reverse=True)

    def test_tiebreak_closer_ranks_first(self):
        """F9A (closer) must rank above F9B (farther) when all other factors equal."""
        eng_results, _ = _run_engine(LISTING_WET_A, [PROC_F9A, PROC_F9B], top_k=2)
        tool_result     = _run_tool(LISTING_WET_A,  [PROC_F9A, PROC_F9B], top_k=2)
        assert eng_results[0].processor_id  == 9,  "engine: closer processor should rank first"
        assert tool_result["matches"][0]["processor_id"] == 9, "tool: closer processor should rank first"


class TestWeightParity:
    """Confirm both implementations use the same weights."""

    def test_weights_identical(self):
        engine_weights = {
            "material":     __import__("matching.engine", fromlist=["WEIGHT_MATERIAL"]).WEIGHT_MATERIAL,
            "capacity":     __import__("matching.engine", fromlist=["WEIGHT_CAPACITY"]).WEIGHT_CAPACITY,
            "distance":     __import__("matching.engine", fromlist=["WEIGHT_DISTANCE"]).WEIGHT_DISTANCE,
            "availability": __import__("matching.engine", fromlist=["WEIGHT_AVAILABILITY"]).WEIGHT_AVAILABILITY,
        }
        tool_weights = {
            "material":     _tool_mod.WEIGHT_MATERIAL,
            "capacity":     _tool_mod.WEIGHT_CAPACITY,
            "distance":     _tool_mod.WEIGHT_DISTANCE,
            "availability": _tool_mod.WEIGHT_AVAILABILITY,
        }
        assert engine_weights == tool_weights, (
            f"Weight mismatch between engine and tool:\n"
            f"  engine: {engine_weights}\n"
            f"  tool:   {tool_weights}"
        )

    def test_max_distance_identical(self):
        from matching.engine import MAX_DISTANCE_KM as eng_max
        assert eng_max == _tool_mod.MAX_DISTANCE_KM, (
            f"MAX_DISTANCE_KM differs: engine={eng_max}, tool={_tool_mod.MAX_DISTANCE_KM}"
        )


class TestFullParity:
    """
    Exhaustive parity: for every eligible processor in ALL_PROCESSORS,
    every numeric field in every score breakdown must match within tolerance.
    """

    FIELDS = [
        "material_score", "quality_score", "quantity_score",
        "distance_score", "distance_km", "availability_score", "composite_score",
    ]

    def test_full_breakdown_parity(self):
        eng_results, _ = _run_engine(LISTING_WET_A, ALL_PROCESSORS, top_k=9)
        tool_result     = _run_tool(LISTING_WET_A,  ALL_PROCESSORS, top_k=9)

        assert len(eng_results) == len(tool_result["matches"]), (
            f"Result count differs: engine={len(eng_results)}, tool={len(tool_result['matches'])}"
        )

        for eng, tol in zip(eng_results, tool_result["matches"]):
            assert eng.processor_id == tol["processor_id"], "Processor ID mismatch"
            for field in self.FIELDS:
                e_val = getattr(eng.score_breakdown, field)
                t_val = tol["score_breakdown"][field]
                tol_val = 0.01 if field == "distance_km" else 1e-6
                assert abs(e_val - t_val) < tol_val, (
                    f"Breakdown field '{field}' differs for processor "
                    f"{eng.processor_id}: engine={e_val}, tool={t_val}"
                )
