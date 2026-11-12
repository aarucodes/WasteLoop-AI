"""WasteLoop AI — Streamlit demo UI. Start with: streamlit run app/streamlit_app.py"""
from __future__ import annotations

import os
from datetime import date, timedelta

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

API = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
MATERIALS = ["WET_ORGANIC", "DRY_PAPER", "DRY_PLASTIC", "DRY_METAL", "E_WASTE", "GLASS", "MIXED"]
GRADES = ["A", "B", "C"]

st.set_page_config(page_title="WasteLoop AI", page_icon="♻️", layout="wide")
st.markdown("""
<style>
.block-container {padding-top: 1.7rem; max-width: 1440px;}
[data-testid="stMetric"] {background: #f4f7f5; border: 1px solid #e1e9e3; padding: 14px; border-radius: 12px;}
.small-muted {color: #64746a; font-size: .88rem;}
</style>
""", unsafe_allow_html=True)


def api(method: str, path: str, **kwargs):
    try:
        timeout = kwargs.pop("timeout", 8)
        response = requests.request(method, f"{API}{path}", timeout=timeout, **kwargs)
        if response.status_code >= 400:
            try: detail = response.json().get("detail", response.text)
            except Exception: detail = response.text
            st.error(f"API error ({response.status_code}): {detail}")
            return None
        return response.json() if response.content else {}
    except requests.RequestException as exc:
        st.error(f"Cannot reach the WasteLoop API at {API}. Start the backend first. ({exc})")
        return None


health = api("GET", "/health")
st.title("♻️ WasteLoop AI")
st.caption("Turning segregated waste listings into explainable resource-recovery matches.")
if not health:
    st.stop()

mock_mode = os.getenv("USE_MOCK_AGENT", "true").lower() in ("true", "1", "yes")
st.info("DEMO MODE · Seeded records are synthetic. Matching is deterministic. Pickups require a separate human approval.")
if mock_mode:
    st.warning("Mock-agent mode is enabled. This local fallback does not count as a live IBM watsonx Orchestrate tool invocation.")

# Fetch shared data once per rerun.
summary = api("GET", "/dashboard/summary") or {}
generators = api("GET", "/generators") or []
processors = api("GET", "/processors") or []
listings = api("GET", "/waste-listings") or []
pickups = api("GET", "/pickups") or []

if summary:
    m = st.columns(5)
    m[0].metric("Generators", summary.get("generators", 0))
    m[1].metric("Processors", summary.get("processors", 0))
    m[2].metric("Open listings", summary.get("open_listings", 0))
    m[3].metric("Waste listed", f"{summary.get('listed_waste_kg', 0):,.0f} kg")
    m[4].metric("Completed pickups", summary.get("completed_pickups", 0))

st.divider()
tab_overview, tab_list, tab_match, tab_pickup, tab_directory = st.tabs(
    ["Overview", "Post waste", "Find matches", "Pickup approvals", "Directory"])

with tab_overview:
    left, right = st.columns([1.3, 1])
    with left:
        st.subheader("Recent waste listings")
        if listings:
            rows = []
            for x in listings[:8]:
                gen = next((g["name"] for g in generators if g["id"] == x["generator_id"]), "Unknown generator")
                rows.append({"ID": x["id"], "Generator": gen, "Material": x["material_type"],
                             "Quantity (kg)": x["quantity_kg"], "Grade": x["quality_grade"],
                             "Status": x["status"], "Synthetic": x["is_synthetic"]})
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else: st.write("No listings yet. Add one in **Post waste**.")
    with right:
        st.subheader("Pickup pipeline")
        counts = {k: summary.get(k, 0) for k in ["proposed_pickups", "approved_pickups", "in_transit_pickups", "completed_pickups"]}
        st.dataframe(pd.DataFrame([{"Stage": k.replace("_pickups", "").replace("_", " ").title(), "Count": v}
                                   for k, v in counts.items()]), use_container_width=True, hide_index=True)
        st.caption(summary.get("impact_note", "Impact is not claimed until independently verified."))

with tab_list:
    st.subheader("Create a waste listing")

    GENERATOR_TYPES = ["APARTMENT", "IT_PARK", "COMMERCIAL", "HOSPITAL", "HOTEL"]

    # ── Step 1: choose or create a generator ──────────────────────────────────
    gen_options_raw = {f"{g['name']} · #{g['id']}": g["id"] for g in generators}
    NEW_OPTION = "+ Add New Generator"
    gen_choices = [NEW_OPTION] + list(gen_options_raw)

    # Restore newly created generator selection across reruns
    default_gen_index = 0
    if st.session_state.get("new_generator_label") in gen_choices:
        default_gen_index = gen_choices.index(st.session_state["new_generator_label"])

    gen_label = st.selectbox(
        "Generator",
        gen_choices,
        index=default_gen_index,
        key=f"gen_selector_{len(generators)}",
        help="Select an existing generator or register a new one.",
    )

    # ── New generator registration form ───────────────────────────────────────
    if gen_label == NEW_OPTION:
        st.info("Fill in the details below to register a new generator, then continue to create the listing.")
        with st.form("register_generator"):
            st.markdown("**Register new generator**")
            new_name = st.text_input("Organisation name", max_chars=200,
                                     help="Minimum 2 characters, maximum 200.")
            new_type = st.selectbox("Generator type", GENERATOR_TYPES)
            new_address = st.text_input("Address", help="Minimum 5 characters.")
            new_pincode = st.text_input("Pincode", max_chars=6,
                                        help="6-digit Bengaluru area pincode.")
            gc1, gc2 = st.columns(2)
            new_lat = gc1.number_input("Latitude", min_value=-90.0, max_value=90.0,
                                       value=12.97, format="%.6f",
                                       help="Decimal degrees, e.g. 12.9716")
            new_lng = gc2.number_input("Longitude", min_value=-180.0, max_value=180.0,
                                       value=77.59, format="%.6f",
                                       help="Decimal degrees, e.g. 77.5946")
            new_email = st.text_input("Contact email")
            reg_submitted = st.form_submit_button("Register generator", type="primary")

        if reg_submitted:
            # Client-side pre-validation mirrors GeneratorCreate rules so the
            # user gets clear feedback before hitting the API.
            errors = []
            if len(new_name.strip()) < 2:
                errors.append("Organisation name must be at least 2 characters.")
            if len(new_address.strip()) < 5:
                errors.append("Address must be at least 5 characters.")
            import re
            if not re.fullmatch(r"\d{6}", new_pincode.strip()):
                errors.append("Pincode must be exactly 6 digits.")
            if not new_email.strip():
                errors.append("Contact email is required.")
            if errors:
                for e in errors:
                    st.error(e)
            else:
                created = api("POST", "/generators", json={
                    "name": new_name.strip(),
                    "type": new_type,
                    "address": new_address.strip(),
                    "pincode": new_pincode.strip(),
                    "lat": new_lat,
                    "lng": new_lng,
                    "contact_email": new_email.strip(),
                    "is_synthetic": False,
                })
                if created:
                    label = f"{created['name']} · #{created['id']}"
                    st.session_state["new_generator_label"] = label
                    st.success(
                        f"Generator **{created['name']}** registered (ID #{created['id']}). "
                        "Now fill in the waste listing details below."
                    )
                    st.rerun()

    # ── Step 2: waste listing form ─────────────────────────────────────────────
    # Resolve the selected generator ID (None when "+ Add New Generator" is still chosen)
    selected_gen_id = gen_options_raw.get(gen_label)

    if selected_gen_id is None:
        st.caption("Register or select a generator above to unlock the waste listing form.")
    else:
        st.divider()
        with st.form("new_listing"):
            st.markdown(f"**Listing for:** {gen_label}")
            c1, c2, c3 = st.columns(3)
            material = c1.selectbox("Material", MATERIALS)
            qty = c2.number_input("Quantity (kg)", min_value=1.0, value=350.0, step=25.0)
            grade = c3.selectbox("Quality grade", GRADES)
            c4, c5 = st.columns(2)
            start = c4.date_input("Available from", value=date.today())
            end = c5.date_input("Available until", value=date.today() + timedelta(days=7))
            description = st.text_area("Description / contamination notes", max_chars=1000)
            submitted = st.form_submit_button("Create listing", type="primary")

        if submitted:
            if end < start:
                st.error("End date must be on or after start date.")
            else:
                result = api("POST", "/waste-listings", json={
                    "generator_id": selected_gen_id,
                    "material_type": material,
                    "quantity_kg": qty,
                    "quality_grade": grade,
                    "available_from": start.isoformat(),
                    "available_until": end.isoformat(),
                    "description": description or None,
                    "is_synthetic": False,
                })
                if result:
                    # Clear the new-generator selection so the dropdown resets
                    st.session_state.pop("new_generator_label", None)
                    st.success(f"Listing #{result['id']} created.")
                    st.rerun()

with tab_match:
    st.subheader("Explainable processor matching")
    if not listings:
        st.info("Create or seed a listing first.")
    else:
        listing_options = {f"#{x['id']} · {x['material_type']} · {x['quantity_kg']:,.0f} kg · {x['status']}": x["id"]
                           for x in listings if x["status"] not in ("CANCELLED", "COMPLETED")}
        if listing_options:
            chosen = st.selectbox("Select a listing", list(listing_options), key="match_listing")
            listing_id = listing_options[chosen]
            if st.button("Ask WasteLoop to find matches", type="primary"):
                with st.spinner("Recomputing eligibility and ranking..."):
                    result = api("POST", "/agent/match", json={"listing_id": listing_id}, timeout=120)
                if result:
                    st.session_state["last_agent_result"] = result
                    st.session_state["last_listing_id"] = listing_id
            result = st.session_state.get("last_agent_result")
            if result and st.session_state.get("last_listing_id") == listing_id:
                st.write(result["narrative"])
                if result["top_matches"]:
                    for rank, match in enumerate(result["top_matches"], 1):
                        with st.container(border=True):
                            a, b = st.columns([3, 1])
                            a.markdown(f"**#{rank} · {match['processor_name']}**")
                            a.caption(f"{match['processor_type']} · {'Synthetic demo record' if match['is_synthetic'] else 'Registered record'}")
                            b.metric("Match score", f"{match['score']:.2f}/1.00")
                            st.write(match["explanation"])
                            bd = match["score_breakdown"]
                            st.caption(f"Distance {bd['distance_km']:.1f} km · Capacity fit {bd['quantity_score']:.2f} · Availability overlap {bd['availability_score']:.0%}")
                            if st.button("Propose pickup", key=f"propose_{listing_id}_{match['processor_id']}"):
                                current = next(x for x in listings if x["id"] == listing_id)
                                proposed = max(date.today(), date.fromisoformat(current["available_from"]))
                                if proposed > date.fromisoformat(current["available_until"]):
                                    st.error("This listing's availability window has expired.")
                                else:
                                    made = api("POST", "/pickups", json={"listing_id": listing_id,
                                        "processor_id": match["processor_id"], "proposed_date": proposed.isoformat(),
                                        "notes": "Proposed from Streamlit matching review."})
                                    if made: st.success(f"Pickup #{made['id']} proposed. It is NOT approved."); st.rerun()
                else: st.warning("No eligible processor found for this listing.")
        else: st.info("No active listings are available for matching.")

with tab_pickup:
    st.subheader("Human pickup approval")
    pending = [p for p in pickups if p["status"] == "PROPOSED"]
    if not pending: st.info("There are no pickup proposals awaiting approval.")
    for p in pending:
        listing = next((x for x in listings if x["id"] == p["listing_id"]), {})
        processor = next((x for x in processors if x["id"] == p["processor_id"]), {})
        with st.container(border=True):
            st.markdown(f"**Pickup #{p['id']} · {processor.get('name', 'Processor')}**")
            st.write(f"Listing #{p['listing_id']} · {listing.get('material_type', '')} · {listing.get('quantity_kg', 0):,.0f} kg · proposed {p['proposed_date']}")
            approver = st.text_input("Approver name / email", key=f"approver_{p['id']}")
            if st.button("Approve pickup", key=f"approve_{p['id']}", type="primary"):
                if not approver.strip(): st.error("Enter the human approver's name or email.")
                else:
                    updated = api("PATCH", f"/pickups/{p['id']}/status", json={"status": "APPROVED", "approved_by": approver.strip()})
                    if updated: st.success(f"Pickup #{p['id']} approved by {approver}."); st.rerun()
    active = [p for p in pickups if p["status"] in ("APPROVED", "IN_TRANSIT")]
    if active:
        st.markdown("**Operational updates**")
        for p in active:
            st.write(f"Pickup #{p['id']} · {p['status']} · listing #{p['listing_id']}")
            next_status = "IN_TRANSIT" if p["status"] == "APPROVED" else "COMPLETED"
            if st.button(f"Mark {next_status.replace('_', ' ').title()}", key=f"advance_{p['id']}"):
                changed = api("PATCH", f"/pickups/{p['id']}/status", json={"status": next_status})
                if changed: st.success(f"Pickup #{p['id']} updated."); st.rerun()

with tab_directory:
    a, b = st.columns(2)
    with a:
        st.subheader("Generators")
        if generators:
            st.dataframe(pd.DataFrame([{"Name": g["name"], "Type": g["type"], "Area": g["address"],
                                        "Synthetic": g["is_synthetic"]} for g in generators]),
                         use_container_width=True, hide_index=True)
    with b:
        st.subheader("Processors")
        if processors:
            st.dataframe(pd.DataFrame([{"Name": p["name"], "Type": p["processor_type"],
                                        "Area": p["address"], "Licence / demo ID": p["licence_number"],
                                        "Synthetic": p["is_synthetic"]} for p in processors]),
                         use_container_width=True, hide_index=True)

st.divider()
st.caption("WasteLoop AI · Local demonstration build · No live licences, processor availability, verified recovery, or carbon savings are represented.")
