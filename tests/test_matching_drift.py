"""
tests/test_matching_drift.py
----------------------------
Drift test: asserts that the inline matching logic in tools/find_waste_matches.py
produces IDENTICAL results to the authoritative matching/engine.py.

Also includes a snapshot-CSV parity test to detect when data/processors.csv or
data/processor_capacity.csv changes without the snapshot being updated.
"""

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from matching.engine import (
    CapacityInput, ListingInput, ProcessorInput,
    find_matches as engine_find_matches,
    is_eligible as engine_is_eligible,
)

import importlib.util, types

def _load_tool_module() -> types.ModuleType:
    # Offline test environments may not install IBM's runtime SDK. The drift
    # tests exercise the wrapped function body only, so provide a test-only
    # decorator shim; the deployed tool file remains unchanged.
    try:
        import ibm_watsonx_orchestrate.agent_builder.tools  # noqa: F401
    except ImportError:
        pkg = types.ModuleType("ibm_watsonx_orchestrate"); pkg.__path__ = []
        sub = types.ModuleType("ibm_watsonx_orchestrate.agent_builder"); sub.__path__ = []
        sdk_tools = types.ModuleType("ibm_watsonx_orchestrate.agent_builder.tools")
        class _Permission:
            READ_ONLY = "read_only"
        def _tool(**_kwargs):
            def decorate(fn):
                return types.SimpleNamespace(fn=fn)
            return decorate
        sdk_tools.ToolPermission = _Permission
        sdk_tools.tool = _tool
        sys.modules.update({
            "ibm_watsonx_orchestrate": pkg,
            "ibm_watsonx_orchestrate.agent_builder": sub,
            "ibm_watsonx_orchestrate.agent_builder.tools": sdk_tools,
        })
    spec = importlib.util.spec_from_file_location(
        "find_waste_matches", ROOT / "tools" / "find_waste_matches.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_tool_mod = _load_tool_module()

# ---------------------------------------------------------------------------
# Shared fixtures (plain dicts, JSON-serialisable)
# ---------------------------------------------------------------------------
TODAY = date(2026, 11, 5)
NEXT_WEEK = date(2026, 11, 12)
NEXT_MONTH = date(2026, 11, 30)

LISTING_WET_A: Dict[str, Any] = {
    "id": 1, "material_type": "WET_ORGANIC", "quantity_kg": 300.0,
    "quality_grade": "A", "available_from": "2026-11-05", "available_until": "2026-11-12",
    "generator_lat": 12.9716, "generator_lng": 77.5946,
}
LISTING_WET_C = {**LISTING_WET_A, "id": 99, "quality_grade": "C"}

def _cap(material="WET_ORGANIC", min_qty=100.0, max_qty=2000.0, grades="A",
         avail_from="2026-11-01", avail_until="2026-11-30", load=0.0) -> Dict:
    return {"material_type": material, "min_quantity_kg": min_qty, "max_quantity_kg": max_qty,
            "accepted_grades": grades, "available_from": avail_from,
            "available_until": avail_until, "current_load_kg": load}

def _make_proc(pid, name, ptype, lat, lng, caps) -> Dict:
    return {"id": pid, "name": name, "processor_type": ptype,
            "lat": lat, "lng": lng, "is_synthetic": True, "capacities": caps}

PROC_F1 = _make_proc(1, "Good Biogas",     "BIOGAS_PLANT",    12.9716, 77.5946, [_cap()])
PROC_F2 = _make_proc(2, "Paper Only",      "PAPER_RECYCLER",  12.97,   77.59,   [_cap(material="DRY_PAPER")])
PROC_F3 = _make_proc(3, "Large Biogas",    "BIOGAS_PLANT",    12.97,   77.59,   [_cap(min_qty=500.0)])
PROC_F4 = _make_proc(4, "Full Biogas",     "BIOGAS_PLANT",    12.97,   77.59,   [_cap(max_qty=1000.0, load=750.0)])
PROC_F5 = _make_proc(5, "Future Biogas",   "BIOGAS_PLANT",    12.97,   77.59,
                     [_cap(avail_from="2026-11-20", avail_until="2026-11-30")])
PROC_F6 = _make_proc(6, "Grade A Only",    "BIOGAS_PLANT",    12.97,   77.59,   [_cap(grades="A")])
PROC_F7 = _make_proc(7, "Partial Window",  "BIOGAS_PLANT",    12.97,   77.59,
                     [_cap(avail_from="2026-11-09", avail_until="2026-11-30")])
PROC_F8 = _make_proc(8, "Distant Biogas",  "BIOGAS_PLANT",    13.33,   77.59,   [_cap()])
PROC_F9A= _make_proc(9, "Close Biogas",    "BIOGAS_PLANT",    12.9716+0.018, 77.5946, [_cap()])
PROC_F9B= _make_proc(10,"Mid Biogas",      "BIOGAS_PLANT",    12.9716+0.090, 77.5946, [_cap()])
ALL_PROCESSORS = [PROC_F1, PROC_F2, PROC_F3, PROC_F4, PROC_F5, PROC_F7, PROC_F8, PROC_F9A, PROC_F9B]

# ---------------------------------------------------------------------------
# Adapters: dict -> engine dataclasses
# ---------------------------------------------------------------------------
def _to_engine_listing(d):
    return ListingInput(
        id=d["id"], material_type=d["material_type"], quantity_kg=d["quantity_kg"],
        quality_grade=d["quality_grade"],
        available_from=date.fromisoformat(d["available_from"]),
        available_until=date.fromisoformat(d["available_until"]),
        generator_lat=d["generator_lat"], generator_lng=d["generator_lng"],
    )

def _to_engine_processor(d):
    caps = [CapacityInput(
        processor_id=d["id"], material_type=c["material_type"],
        min_quantity_kg=c["min_quantity_kg"], max_quantity_kg=c["max_quantity_kg"],
        accepted_grades=c["accepted_grades"],
        available_from=date.fromisoformat(c["available_from"]),
        available_until=date.fromisoformat(c["available_until"]),
        current_load_kg=c["current_load_kg"],
    ) for c in d["capacities"]]
    return ProcessorInput(id=d["id"], name=d["name"], processor_type=d["processor_type"],
                          lat=d["lat"], lng=d["lng"], is_synthetic=d["is_synthetic"],
                          capacities=caps)

# ---------------------------------------------------------------------------
# Runners
# ---------------------------------------------------------------------------
def _run_engine(listing_d, proc_dicts, top_k=5):
    listing = _to_engine_listing(listing_d)
    procs   = [_to_engine_processor(p) for p in proc_dicts]
    return engine_find_matches(listing, procs, top_k=top_k)

def _run_tool(listing_d, top_k=5):
    """Run the tool's fn() directly using the embedded snapshot."""
    result = _tool_mod.find_waste_matches.fn(
        listing_id=listing_d["id"],
        material_type=listing_d["material_type"],
        quantity_kg=listing_d["quantity_kg"],
        quality_grade=listing_d["quality_grade"],
        available_from=listing_d["available_from"],
        available_until=listing_d["available_until"],
        generator_lat=listing_d["generator_lat"],
        generator_lng=listing_d["generator_lng"],
        top_k=top_k,
    )
    if hasattr(result, "model_dump"):
        d = result.model_dump()
        d["matches"] = json.loads(d["top_matches"])
        return d
    return result

def _snapshot_proc_ids(material):
    """Return processor IDs from the tool snapshot that have a cap for material."""
    return sorted(p["id"] for p in _tool_mod._SNAPSHOT
                  if any(c["mat"] == material for c in p["caps"]))

def _engine_proc_ids(proc_dicts, material):
    return sorted(p["id"] for p in proc_dicts
                  if any(c["material_type"] == material for c in p["capacities"]))

# ---------------------------------------------------------------------------
# Snapshot CSV parity
# ---------------------------------------------------------------------------

class TestSnapshotCSVParity:
    """Every field embedded in the tool snapshot must match the source CSVs."""

    def test_processor_fields_match_csv(self):
        import pandas as pd
        df = pd.read_csv(ROOT / "data" / "processors.csv").set_index("id")
        snapshot = {p["id"]: p for p in _tool_mod._SNAPSHOT}
        assert set(snapshot) == set(int(x) for x in df.index)
        field_map = {"name": "name", "processor_type": "type", "lat": "lat",
                     "lng": "lng", "is_synthetic": "synthetic"}
        for pid, row in df.iterrows():
            snap = snapshot[int(pid)]
            for csv_field, snap_field in field_map.items():
                expected = row[csv_field]
                actual = snap[snap_field]
                if csv_field in ("lat", "lng"):
                    assert float(actual) == pytest.approx(float(expected), abs=1e-6), (pid, snap_field)
                elif csv_field == "is_synthetic":
                    assert bool(actual) == bool(expected)
                else:
                    assert actual == expected, (pid, snap_field, actual, expected)

    def test_every_capacity_field_matches_csv(self):
        import pandas as pd
        from collections import Counter
        df = pd.read_csv(ROOT / "data" / "processor_capacity.csv")
        snapshot = {p["id"]: p for p in _tool_mod._SNAPSHOT}
        assert sum(len(p["caps"]) for p in snapshot.values()) == len(df)
        for pid, group in df.groupby("processor_id"):
            assert int(pid) in snapshot, f"Processor {pid} missing from snapshot"
            csv_rows = Counter()
            for _, r in group.iterrows():
                csv_rows[(str(r.material_type), float(r.min_quantity_kg),
                          float(r.max_quantity_kg), str(r.accepted_grades),
                          str(r.available_from), str(r.available_until),
                          float(r.current_load_kg))] += 1
            snap_rows = Counter()
            for c in snapshot[int(pid)]["caps"]:
                snap_rows[(str(c["mat"]), float(c["min"]), float(c["max"]),
                           str(c["grades"]), str(c["from"]), str(c["until"]),
                           float(c["load"]))] += 1
            assert csv_rows == snap_rows, f"Processor {pid}: capacity snapshot differs from CSV"

    def test_snapshot_id_present(self):
        assert hasattr(_tool_mod, "SNAPSHOT_ID")
        assert _tool_mod.SNAPSHOT_ID.startswith("wasteloop-snapshot-")

    def test_all_synthetic(self):
        for p in _tool_mod._SNAPSHOT:
            assert p["synthetic"] is True, f"Processor {p['id']} not marked synthetic"

# ---------------------------------------------------------------------------
# Weight parity
# ---------------------------------------------------------------------------

class TestWeightParity:
    def test_weights_identical(self):
        from matching.engine import (WEIGHT_MATERIAL, WEIGHT_CAPACITY,
                                      WEIGHT_DISTANCE, WEIGHT_AVAILABILITY)
        assert WEIGHT_MATERIAL     == _tool_mod.WEIGHT_MATERIAL
        assert WEIGHT_CAPACITY     == _tool_mod.WEIGHT_CAPACITY
        assert WEIGHT_DISTANCE     == _tool_mod.WEIGHT_DISTANCE
        assert WEIGHT_AVAILABILITY == _tool_mod.WEIGHT_AVAILABILITY

    def test_max_distance_identical(self):
        from matching.engine import MAX_DISTANCE_KM
        assert MAX_DISTANCE_KM == _tool_mod.MAX_DISTANCE_KM

    def test_weights_sum_to_one(self):
        total = (_tool_mod.WEIGHT_MATERIAL + _tool_mod.WEIGHT_CAPACITY
                 + _tool_mod.WEIGHT_DISTANCE + _tool_mod.WEIGHT_AVAILABILITY)
        assert abs(total - 1.0) < 1e-9

# ---------------------------------------------------------------------------
# Eligible-set parity (engine fixture processors vs snapshot)
# ---------------------------------------------------------------------------

class TestEligibleSet:
    """For the snapshot WET_ORGANIC processors, both implementations must agree on eligibility."""

    def _snap_eligible_ids(self, listing_d, top_k=20):
        r = _run_tool(listing_d, top_k=top_k)
        return sorted(m["processor_id"] for m in r["matches"])

    def _eng_eligible_ids(self, listing_d, top_k=20):
        # Build engine processors from the snapshot data for apples-to-apples comparison
        procs = []
        for p in _tool_mod._SNAPSHOT:
            caps = [CapacityInput(
                processor_id=p["id"], material_type=c["mat"],
                min_quantity_kg=c["min"], max_quantity_kg=c["max"],
                accepted_grades=c["grades"],
                available_from=date.fromisoformat(c["from"]),
                available_until=date.fromisoformat(c["until"]),
                current_load_kg=c["load"],
            ) for c in p["caps"]]
            procs.append(ProcessorInput(
                id=p["id"], name=p["name"], processor_type=p["type"],
                lat=p["lat"], lng=p["lng"], is_synthetic=True, capacities=caps))
        listing = _to_engine_listing(listing_d)
        results, _ = engine_find_matches(listing, procs, top_k=top_k)
        return sorted(r.processor_id for r in results)

    def test_wet_organic_eligible_set_matches(self):
        snap = self._snap_eligible_ids(LISTING_WET_A)
        eng  = self._eng_eligible_ids(LISTING_WET_A)
        assert snap == eng, f"Eligible set differs: tool={snap}, engine={eng}"

    def test_grade_c_filtered_out(self):
        snap = self._snap_eligible_ids(LISTING_WET_C)
        eng  = self._eng_eligible_ids(LISTING_WET_C)
        assert snap == eng

# ---------------------------------------------------------------------------
# Score parity: engine (snapshot procs) vs tool snapshot
# ---------------------------------------------------------------------------

class TestScoreParity:
    TOL = 1e-4

    def _both(self, listing_d, top_k=20):
        """Run both implementations on the same snapshot data."""
        procs_engine = []
        for p in _tool_mod._SNAPSHOT:
            caps = [CapacityInput(
                processor_id=p["id"], material_type=c["mat"],
                min_quantity_kg=c["min"], max_quantity_kg=c["max"],
                accepted_grades=c["grades"],
                available_from=date.fromisoformat(c["from"]),
                available_until=date.fromisoformat(c["until"]),
                current_load_kg=c["load"],
            ) for c in p["caps"]]
            procs_engine.append(ProcessorInput(
                id=p["id"], name=p["name"], processor_type=p["type"],
                lat=p["lat"], lng=p["lng"], is_synthetic=True, capacities=caps))
        listing = _to_engine_listing(listing_d)
        eng_results, _ = engine_find_matches(listing, procs_engine, top_k=top_k)
        tool_result     = _run_tool(listing_d, top_k=top_k)
        return eng_results, tool_result["matches"]

    def test_ranking_order_matches(self):
        eng, tool = self._both(LISTING_WET_A)
        assert [r.processor_id for r in eng] == [m["processor_id"] for m in tool]

    def test_composite_scores_match(self):
        eng, tool = self._both(LISTING_WET_A)
        for e, t in zip(eng, tool):
            assert abs(e.score - t["score"]) < self.TOL, (
                f"Score mismatch proc {e.processor_id}: engine={e.score}, tool={t['score']}")

    def test_breakdown_fields_match(self):
        FIELDS = ["material_score","quality_score","quantity_score",
                  "distance_score","availability_score","composite_score"]
        eng, tool = self._both(LISTING_WET_A)
        for e, t in zip(eng, tool):
            for f in FIELDS:
                ev = getattr(e.score_breakdown, f)
                tv = t["score_breakdown"][f]
                assert abs(ev - tv) < self.TOL, (
                    f"Field '{f}' proc {e.processor_id}: engine={ev}, tool={tv}")

    def test_distance_km_within_tolerance(self):
        eng, tool = self._both(LISTING_WET_A)
        for e, t in zip(eng, tool):
            assert abs(e.score_breakdown.distance_km - t["score_breakdown"]["distance_km"]) < 0.01

# ---------------------------------------------------------------------------
# Tool output fields
# ---------------------------------------------------------------------------

class TestToolOutputFields:
    def test_snapshot_id_in_output(self):
        r = _run_tool(LISTING_WET_A)
        assert r["snapshot_id"] == _tool_mod.SNAPSHOT_ID

    def test_processor_count_in_output(self):
        r = _run_tool(LISTING_WET_A)
        assert r["processor_count"] == len(_tool_mod._SNAPSHOT)

    def test_recommended_id_is_top_match(self):
        r = _run_tool(LISTING_WET_A)
        if r["matches"]:
            assert r["recommended_processor_id"] == r["matches"][0]["processor_id"]

    def test_no_match_returns_minus_one(self):
        bad = {**LISTING_WET_A, "material_type": "MIXED"}
        r = _run_tool(bad)
        assert r["recommended_processor_id"] == -1

    def test_top_matches_is_valid_json(self):
        r = _run_tool(LISTING_WET_A)
        parsed = json.loads(r["top_matches"]) if isinstance(r["top_matches"], str) else r["top_matches"]
        assert isinstance(parsed, list)

    def test_total_eligible_leq_total_candidates(self):
        r = _run_tool(LISTING_WET_A)
        assert r["total_eligible"] <= r["total_candidates"]

    def test_approval_boundary_not_in_engine(self):
        import inspect
        import matching.engine as eng_mod
        src = inspect.getsource(eng_mod)
        assert "APPROVED" not in src
