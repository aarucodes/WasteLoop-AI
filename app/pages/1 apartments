"""Apartments portal: post waste and report on its pickup. URL: /Apartments"""
from datetime import date, timedelta

import pandas as pd
import streamlit as st
from common import api

MATERIALS = ["WET_ORGANIC", "DRY_PAPER", "DRY_PLASTIC", "DRY_METAL", "E_WASTE", "GLASS", "MIXED"]

st.set_page_config(page_title="Apartments · WasteLoop", page_icon="🏢", layout="wide")
st.title("🏢 Apartments portal")
st.caption("Post segregated waste, then track and report its pickup. Demo build, synthetic data.")

apartments = [g for g in (api("GET", "/generators") or []) if g["type"] == "APARTMENT"]
if not apartments:
    st.warning("No apartment communities are registered.")
    st.stop()
opts = {g["name"]: g["id"] for g in apartments}
gid = opts[st.selectbox("Your apartment community", list(opts))]

tab_post, tab_track = st.tabs(["Post waste", "My listings & pickup reports"])

with tab_post:
    with st.form("post_waste"):
        c1, c2, c3 = st.columns(3)
        material = c1.selectbox("Material", MATERIALS)
        qty = c2.number_input("Quantity (kg)", min_value=1.0, value=100.0, step=10.0)
        grade = c3.selectbox("Quality grade", ["A", "B", "C"])
        c4, c5 = st.columns(2)
        start = c4.date_input("Available from", value=date.today())
        end = c5.date_input("Available until", value=date.today() + timedelta(days=7))
        notes = st.text_area("Description / contamination notes", max_chars=1000)
        go = st.form_submit_button("Post waste", type="primary")
    if go:
        if end < start:
            st.error("End date must be on or after start date.")
        elif r := api("POST", "/waste-listings", json={
                "generator_id": gid, "material_type": material, "quantity_kg": qty,
                "quality_grade": grade, "available_from": start.isoformat(),
                "available_until": end.isoformat(), "description": notes or None,
                "is_synthetic": False}):
            st.success(f"Listing #{r['id']} posted. Processors can now accept it.")

with tab_track:
    listings = [x for x in (api("GET", "/waste-listings") or []) if x["generator_id"] == gid]
    pickups = api("GET", "/pickups") or []
    procs = {p["id"]: p["name"] for p in (api("GET", "/processors") or [])}
    if not listings:
        st.info("Nothing posted yet.")
    for x in listings:
        pk = next((p for p in pickups if p["listing_id"] == x["id"] and p["status"] != "CANCELLED"), None)
        with st.container(border=True):
            st.markdown(f"**Listing #{x['id']} · {x['material_type']} · {x['quantity_kg']:,.0f} kg** · {x['status']}")
            if not pk:
                st.caption("Waiting for a processor to accept.")
                continue
            st.write(f"Pickup #{pk['id']} · {procs.get(pk['processor_id'], 'Processor')} · "
                     f"{pk['proposed_date']} · **{pk['status']}**")
            a, b = st.columns(2)
            if pk["status"] == "IN_TRANSIT" and a.button("Confirm collected", key=f"ok{pk['id']}", type="primary"):
                if api("PATCH", f"/pickups/{pk['id']}/status", json={"status": "COMPLETED"}) is not None:
                    st.rerun()
            if pk["status"] in ("PROPOSED", "APPROVED", "IN_TRANSIT"):
                with b.popover("Report a problem"):
                    why = st.text_input("What went wrong?", key=f"why{pk['id']}")
                    if st.button("Cancel pickup & report", key=f"bad{pk['id']}"):
                        if not why.strip():
                            st.error("Describe the problem.")
                        elif api("PATCH", f"/pickups/{pk['id']}/status",
                                 json={"status": "CANCELLED", "notes": f"Reported by apartment: {why.strip()}"}) is not None:
                            st.rerun()