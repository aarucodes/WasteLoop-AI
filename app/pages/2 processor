"""Processor portal: accept incoming waste and run pickups. URL: /Processor"""
from datetime import date

import streamlit as st
from common import api

st.set_page_config(page_title="Processor · WasteLoop", page_icon="🏭", layout="wide")
st.title("🏭 Processor portal")
st.caption("Accept eligible waste and move pickups through to completion. Demo build, synthetic data.")

procs = api("GET", "/processors") or []
if not procs:
    st.warning("No processors are registered.")
    st.stop()
opts = {p["name"]: p["id"] for p in procs}
pid = opts[st.selectbox("Your processing unit", list(opts))]
who = st.text_input("Your name / email (recorded as the human approver)")

listings = {x["id"]: x for x in (api("GET", "/waste-listings") or [])}
gens = {g["id"]: g["name"] for g in (api("GET", "/generators") or [])}
pickups = api("GET", "/pickups") or []
mine = [p for p in pickups if p["processor_id"] == pid]
taken = {p["listing_id"] for p in pickups if p["status"] != "CANCELLED"}


def line(x):
    return (f"Listing #{x['id']} · {gens.get(x['generator_id'], '?')} · {x['material_type']} · "
            f"{x['quantity_kg']:,.0f} kg · grade {x['quality_grade']}")


def accept(listing, pickup=None):
    if not who.strip():
        st.error("Enter your name / email to accept.")
        return
    if pickup is None:  # backend re-validates eligibility here
        start = max(date.today(), date.fromisoformat(listing["available_from"]))
        pickup = api("POST", "/pickups", json={"listing_id": listing["id"], "processor_id": pid,
                                               "proposed_date": start.isoformat(),
                                               "notes": "Accepted from Processor portal."})
    if pickup and api("PATCH", f"/pickups/{pickup['id']}/status",
                      json={"status": "APPROVED", "approved_by": who.strip()}) is not None:
        st.rerun()


tab_in, tab_jobs = st.tabs(["Incoming waste", "My pickups"])

with tab_in:
    shown = False
    for p in (p for p in mine if p["status"] == "PROPOSED"):  # proposed from the main app
        x = listings[p["listing_id"]]
        shown = True
        with st.container(border=True):
            st.markdown(f"**Proposed pickup #{p['id']}** · {line(x)} · {p['proposed_date']}")
            a, b = st.columns(2)
            if a.button("Accept", key=f"acc{p['id']}", type="primary"): accept(x, p)
            if b.button("Decline", key=f"dec{p['id']}"):
                if api("PATCH", f"/pickups/{p['id']}/status", json={"status": "CANCELLED"}) is not None:
                    st.rerun()
    for x in (x for x in listings.values() if x["status"] == "OPEN" and x["id"] not in taken):
        res = api("GET", f"/matching/{x['id']}", params={"top_k": 20})
        m = next((m for m in (res or {}).get("top_matches", []) if m["processor_id"] == pid), None)
        if not m:
            continue  # not eligible for this processor
        shown = True
        with st.container(border=True):
            st.markdown(f"**{line(x)}**")
            st.caption(f"Match {m['score']:.2f}/1.00 · {m['score_breakdown']['distance_km']:.1f} km · {m['explanation']}")
            if st.button("Accept pickup", key=f"new{x['id']}", type="primary"): accept(x)
    if not shown:
        st.info("No eligible waste waiting for you right now.")

with tab_jobs:
    active = [p for p in mine if p["status"] in ("APPROVED", "IN_TRANSIT")]
    if not active:
        st.info("No active pickups.")
    for p in active:
        nxt = "IN_TRANSIT" if p["status"] == "APPROVED" else "COMPLETED"
        with st.container(border=True):
            st.markdown(f"**Pickup #{p['id']} · {p['status']}** · {line(listings[p['listing_id']])} · {p['proposed_date']}")
            if st.button(f"Mark {nxt.replace('_', ' ').title()}", key=f"adv{p['id']}", type="primary"):
                if api("PATCH", f"/pickups/{p['id']}/status", json={"status": nxt}) is not None:
                    st.rerun()