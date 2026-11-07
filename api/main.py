"""WasteLoop AI FastAPI application.

The API is the trusted boundary: matching is always recomputed locally before a
pickup can be proposed, and only an explicit human status action can approve it.
"""

from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Any



from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, joinedload

from api import models, schemas
from api.database import get_db, init_db
from matching.engine import (
    CapacityInput, ListingInput, ProcessorInput, find_matches, is_eligible,
)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="WasteLoop AI API", version="1.0.0",
              description="Synthetic demonstration platform for waste-to-resource matching.",
              lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
    allow_credentials=False, allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"])



def _listing_input(db: Session, listing: models.WasteListing) -> ListingInput:
    generator = db.get(models.Generator, listing.generator_id)
    if generator is None:
        raise HTTPException(409, "Listing has no valid generator")
    return ListingInput(
        id=listing.id, material_type=listing.material_type.value,
        quantity_kg=listing.quantity_kg, quality_grade=listing.quality_grade.value,
        available_from=listing.available_from, available_until=listing.available_until,
        generator_lat=generator.lat, generator_lng=generator.lng)


def _processor_inputs(db: Session) -> list[ProcessorInput]:
    processors = (db.query(models.Processor)
                  .options(joinedload(models.Processor.capacities)).all())
    result: list[ProcessorInput] = []
    for p in processors:
        caps = [CapacityInput(
            processor_id=p.id, material_type=c.material_type.value,
            min_quantity_kg=c.min_quantity_kg, max_quantity_kg=c.max_quantity_kg,
            accepted_grades=c.accepted_grades, available_from=c.available_from,
            available_until=c.available_until, current_load_kg=c.current_load_kg)
            for c in p.capacities]
        result.append(ProcessorInput(
            id=p.id, name=p.name, processor_type=p.processor_type.value,
            lat=p.lat, lng=p.lng, is_synthetic=p.is_synthetic, capacities=caps))
    return result


def _match_payload(result: Any, processor: models.Processor) -> dict[str, Any]:
    b = result.score_breakdown
    return {
        "processor_id": result.processor_id, "processor_name": result.processor_name,
        "processor_type": result.processor_type, "score": result.score,
        "score_breakdown": {
            "material_score": b.material_score, "quantity_score": b.quantity_score,
            "quality_score": b.quality_score, "distance_score": b.distance_score,
            "distance_km": b.distance_km, "availability_score": b.availability_score,
            "composite_score": b.composite_score},
        "explanation": result.explanation, "is_synthetic": result.is_synthetic,
    }



def _run_watsonx_agent(
    listing: models.WasteListing,
    listing_data: ListingInput,
) -> tuple[dict[str, Any], str]:
    """Run the deployed WasteLoop agent and return its structured tool result."""
    load_dotenv()

    url = os.getenv("ORCHESTRATE_INSTANCE_URL")
    api_key = os.getenv("ORCHESTRATE_API_KEY")
    agent_id = os.getenv("ORCHESTRATE_AGENT_ID")

    if not all((url, api_key, agent_id)):
        raise HTTPException(
            503, "Orchestrate configuration is incomplete."
        )

    try:
        from ibm_watsonx_orchestrate_clients.common.credentials import Credentials
        from ibm_watsonx_orchestrate_clients.common.client import Client
        from ibm_watsonx_orchestrate_clients.chat.run_client import RunClient

        client = Client(
            credentials=Credentials(url=url, api_key=api_key)
        )
        authenticator = client.service_instance._get_authenticator(
            client.service_instance._infer_auth_type()
        )
        run_client = RunClient(
            base_url=url,
            authenticator=authenticator,
            verify=True,
        )

        message = (
            f"Find the top 3 eligible processor matches for waste listing "
            f"ID {listing.id}. "
            f"Quantity: {listing_data.quantity_kg} kg. "
            f"Material: {listing_data.material_type}. "
            f"Quality grade: {listing_data.quality_grade}. "
            f"Generator coordinates: latitude {listing_data.generator_lat}, "
            f"longitude {listing_data.generator_lng}. "
            f"Available from {listing_data.available_from.isoformat()} "
            f"to {listing_data.available_until.isoformat()}. "
            "Explain the ranking and suggest a pickup date. "
            "Do not approve or create a pickup."
        )

        run = run_client.create_run(
            message=message,
            agent_id=agent_id,
        )

        run_id = run.get("run_id")
        if not run_id:
            raise RuntimeError("Orchestrate did not return a run ID.")

        status = run_client.wait_for_run_completion(
            run_id,
            poll_interval=2,
            max_retries=60,
        )

        if status.get("status") != "completed":
            raise RuntimeError("The Orchestrate agent run did not complete.")

        assistant_message = (
            status.get("result", {})
            .get("data", {})
            .get("message", {})
        )

        # Confirm that the agent actually returned a response.
        response_text = " ".join(
            item.get("text", "")
            for item in assistant_message.get("content", [])
        )
        if not response_text.strip():
            raise RuntimeError("The agent returned an empty response.")

        # Extract the structured output from find_waste_matches.
        tool_result = None
        for step in assistant_message.get("step_history", []):
            for detail in step.get("step_details", []):
                if (
                    detail.get("type") == "tool_response"
                    and detail.get("name") == "find_waste_matches"
                ):
                    tool_result = json.loads(detail.get("content", "{}"))

        if not tool_result or "top_matches" not in tool_result:
            raise RuntimeError(
                "The agent did not return structured matching results."
            )

        return tool_result, run_id

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            502,
            "The live WasteLoop AI agent could not complete the matching request. "
            "Check the Orchestrate service and backend logs."
        )



@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "wasteloop-api"}


@app.get("/generators", response_model=list[schemas.Generator])
def list_generators(db: Session = Depends(get_db)):
    return db.query(models.Generator).order_by(models.Generator.id).all()

@app.post("/generators", response_model=schemas.Generator, status_code=201)
def create_generator(payload: schemas.GeneratorCreate, db: Session = Depends(get_db)):
    obj = models.Generator(**payload.model_dump())
    db.add(obj); db.commit(); db.refresh(obj)
    return obj

@app.get("/processors", response_model=list[schemas.Processor])
def list_processors(db: Session = Depends(get_db)):
    return db.query(models.Processor).order_by(models.Processor.id).all()

@app.post("/processors", response_model=schemas.Processor, status_code=201)
def create_processor(payload: schemas.ProcessorCreate, db: Session = Depends(get_db)):
    obj = models.Processor(**payload.model_dump())
    db.add(obj); db.commit(); db.refresh(obj)
    return obj

@app.get("/processor-capacities", response_model=list[schemas.ProcessorCapacity])
def list_capacities(db: Session = Depends(get_db)):
    return db.query(models.ProcessorCapacity).order_by(models.ProcessorCapacity.id).all()

@app.post("/processor-capacities", response_model=schemas.ProcessorCapacity, status_code=201)
def create_capacity(payload: schemas.ProcessorCapacityCreate, db: Session = Depends(get_db)):
    if db.get(models.Processor, payload.processor_id) is None:
        raise HTTPException(404, "Processor not found")
    if payload.available_until < payload.available_from:
        raise HTTPException(422, "available_until must be on or after available_from")
    obj = models.ProcessorCapacity(**payload.model_dump())
    db.add(obj); db.commit(); db.refresh(obj)
    return obj

@app.get("/waste-listings", response_model=list[schemas.WasteListing])
def list_waste_listings(status: models.ListingStatus | None = None,
                        db: Session = Depends(get_db)):
    q = db.query(models.WasteListing)
    if status is not None: q = q.filter(models.WasteListing.status == status)
    return q.order_by(models.WasteListing.id.desc()).all()

@app.post("/waste-listings", response_model=schemas.WasteListing, status_code=201)
def create_waste_listing(payload: schemas.WasteListingCreate, db: Session = Depends(get_db)):
    if db.get(models.Generator, payload.generator_id) is None:
        raise HTTPException(404, "Generator not found")
    if payload.available_until < payload.available_from:
        raise HTTPException(422, "available_until must be on or after available_from")
    obj = models.WasteListing(**payload.model_dump())
    db.add(obj); db.commit(); db.refresh(obj)
    return obj

@app.get("/matching/{listing_id}", response_model=schemas.MatchResponse)
def get_matches(listing_id: int, top_k: int = Query(5, ge=1, le=20),
                db: Session = Depends(get_db)):
    listing = db.get(models.WasteListing, listing_id)
    if listing is None: raise HTTPException(404, "Waste listing not found")
    if listing.status == models.ListingStatus.CANCELLED:
        raise HTTPException(409, "Cancelled listings cannot be matched")
    ranked, evaluated = find_matches(_listing_input(db, listing), _processor_inputs(db), top_k=top_k)
    return {"listing_id": listing_id,
            "top_matches": [_match_payload(r, db.get(models.Processor, r.processor_id)) for r in ranked],
            "total_candidates_evaluated": evaluated}

@app.post("/pickups", response_model=schemas.Pickup, status_code=201)
def propose_pickup(payload: schemas.PickupCreate, db: Session = Depends(get_db)):
    """Create PROPOSED only, after recomputing current eligibility server-side."""
    listing = db.get(models.WasteListing, payload.listing_id)
    processor = db.get(models.Processor, payload.processor_id)
    if listing is None: raise HTTPException(404, "Waste listing not found")
    if processor is None: raise HTTPException(404, "Processor not found")
    if listing.status in (models.ListingStatus.CANCELLED, models.ListingStatus.COMPLETED):
        raise HTTPException(409, "This listing is not open for a new pickup")
    if not (listing.available_from <= payload.proposed_date <= listing.available_until):
        raise HTTPException(422, "Proposed pickup date must fall within the listing availability window")
    if db.query(models.Pickup).filter(
        models.Pickup.listing_id == listing.id,
        models.Pickup.status != models.PickupStatus.CANCELLED).first():
        raise HTTPException(409, "A non-cancelled pickup already exists for this listing")

    li = _listing_input(db, listing)
    pi = next((p for p in _processor_inputs(db) if p.id == processor.id), None)
    if pi is None: raise HTTPException(409, "Processor has no capacity records")
    eligible_caps = [c for c in pi.capacities if is_eligible(li, c)[0]
                     and c.available_from <= payload.proposed_date <= c.available_until]
    if not eligible_caps:
        raise HTTPException(409, "Processor is not currently eligible for this listing")
    ranked, _ = find_matches(li, [pi], top_k=1)
    if not ranked: raise HTTPException(409, "Processor did not pass matching eligibility")

    match = None
    if payload.match_id is not None:
        match = db.get(models.Match, payload.match_id)
        if match is None or match.listing_id != listing.id or match.processor_id != processor.id:
            raise HTTPException(422, "match_id does not belong to this listing and processor")
    else:
        r = ranked[0]; b = r.score_breakdown
        match = models.Match(
            listing_id=listing.id, processor_id=processor.id, score=r.score,
            score_breakdown=json.dumps({k: getattr(b, k) for k in (
                "material_score", "quantity_score", "quality_score", "distance_score",
                "distance_km", "availability_score", "composite_score")}),
            explanation=r.explanation, recommended_by=models.RecommendedBy.SYSTEM)
        db.add(match); db.flush()

    pickup = models.Pickup(match_id=match.id, listing_id=listing.id,
        processor_id=processor.id, proposed_date=payload.proposed_date,
        status=models.PickupStatus.PROPOSED, notes=payload.notes)
    db.add(pickup); db.commit(); db.refresh(pickup)
    return pickup

_ALLOWED_TRANSITIONS = {
    models.PickupStatus.PROPOSED: {models.PickupStatus.APPROVED, models.PickupStatus.CANCELLED},
    models.PickupStatus.APPROVED: {models.PickupStatus.IN_TRANSIT, models.PickupStatus.CANCELLED},
    models.PickupStatus.IN_TRANSIT: {models.PickupStatus.COMPLETED, models.PickupStatus.CANCELLED},
    models.PickupStatus.COMPLETED: set(), models.PickupStatus.CANCELLED: set(),
}

@app.patch("/pickups/{pickup_id}/status", response_model=schemas.Pickup)
def update_pickup_status(pickup_id: int, payload: schemas.PickupStatusUpdate,
                         db: Session = Depends(get_db)):
    pickup = db.get(models.Pickup, pickup_id)
    if pickup is None: raise HTTPException(404, "Pickup not found")
    target = payload.status
    if target not in _ALLOWED_TRANSITIONS[pickup.status]:
        raise HTTPException(409, f"Invalid pickup transition: {pickup.status.value} -> {target.value}")
    if target == models.PickupStatus.APPROVED and not (payload.approved_by or "").strip():
        raise HTTPException(422, "approved_by is required for human approval")
    listing = db.get(models.WasteListing, pickup.listing_id)
    capacity_rows = (db.query(models.ProcessorCapacity).filter(
        models.ProcessorCapacity.processor_id == pickup.processor_id,
        models.ProcessorCapacity.material_type == listing.material_type)
        .order_by(models.ProcessorCapacity.id).all())
    cap = None
    if target == models.PickupStatus.APPROVED:
        li = _listing_input(db, listing)
        cap = next((row for row in capacity_rows if (is_eligible(li, CapacityInput(
            processor_id=row.processor_id, material_type=row.material_type.value,
            min_quantity_kg=row.min_quantity_kg, max_quantity_kg=row.max_quantity_kg,
            accepted_grades=row.accepted_grades, available_from=row.available_from,
            available_until=row.available_until, current_load_kg=row.current_load_kg))[0]
            and row.available_from <= pickup.proposed_date <= row.available_until)), None)
        if cap is None:
            raise HTTPException(409, "Processor no longer has an eligible capacity window")
        cap.current_load_kg += listing.quantity_kg
        pickup.approved_by = payload.approved_by.strip()
        pickup.approved_at = datetime.now(timezone.utc).replace(tzinfo=None)
        listing.status = models.ListingStatus.PICKUP_SCHEDULED
    elif target in (models.PickupStatus.COMPLETED, models.PickupStatus.CANCELLED):
        if pickup.status in (models.PickupStatus.APPROVED, models.PickupStatus.IN_TRANSIT):
            # The model does not persist a capacity-row FK on Pickup. Release from
            # the first same-material row carrying at least this committed quantity.
            cap = next((row for row in capacity_rows
                        if row.current_load_kg >= listing.quantity_kg), None)
            if cap is not None:
                cap.current_load_kg = max(0.0, cap.current_load_kg - listing.quantity_kg)
        if target == models.PickupStatus.COMPLETED:
            listing.status = models.ListingStatus.COMPLETED
        elif listing.status == models.ListingStatus.PICKUP_SCHEDULED:
            listing.status = models.ListingStatus.OPEN
    pickup.status = target
    if payload.notes: pickup.notes = payload.notes
    db.commit(); db.refresh(pickup)
    return pickup

@app.get("/pickups", response_model=list[schemas.Pickup])
def list_pickups(status: models.PickupStatus | None = None, db: Session = Depends(get_db)):
    q = db.query(models.Pickup)
    if status is not None: q = q.filter(models.Pickup.status == status)
    return q.order_by(models.Pickup.id.desc()).all()

@app.get("/dashboard/summary")
def dashboard_summary(db: Session = Depends(get_db)):
    listings = db.query(models.WasteListing).all()
    pickups = db.query(models.Pickup).all()
    by_status = {s.value: sum(1 for p in pickups if p.status == s) for s in models.PickupStatus}
    return {
        "generators": db.query(models.Generator).count(),
        "processors": db.query(models.Processor).count(),
        "listings": len(listings),
        "open_listings": sum(1 for x in listings if x.status == models.ListingStatus.OPEN),
        "listed_waste_kg": round(sum(x.quantity_kg for x in listings), 2),
        "proposed_pickups": by_status["PROPOSED"],
        "approved_pickups": by_status["APPROVED"],
        "in_transit_pickups": by_status["IN_TRANSIT"],
        "completed_pickups": by_status["COMPLETED"],
        "verified_recovery_kg": None,
        "impact_note": "Recovery and environmental impact are not claimed until a completed pickup is independently verified.",
    }


@app.post("/agent/match", response_model=schemas.AgentResponse)
def agent_match(payload: schemas.AgentRunRequest, db: Session = Depends(get_db)):
    """Run live or mock matching. Never creates or approves a pickup."""
    listing = db.get(models.WasteListing, payload.listing_id)
    if listing is None:
        raise HTTPException(404, "Waste listing not found")

    if listing.status == models.ListingStatus.CANCELLED:
        raise HTTPException(409, "Cancelled listings cannot be matched")

    listing_data = _listing_input(db, listing)

    # Independently recompute matches using the API's trusted local database.
    ranked, evaluated = find_matches(
        listing_data, _processor_inputs(db), top_k=3
    )
    results = [
        _match_payload(r, db.get(models.Processor, r.processor_id))
        for r in ranked
    ]

    use_mock = os.getenv("USE_MOCK_AGENT", "true").lower() in (
        "1", "true", "yes"
    )

    if use_mock:
        if results:
            narrative = (
                f"Mock matching evaluated {evaluated} processor candidates. "
                f"The strongest eligible match is {results[0]['processor_name']} "
                f"with a score of {results[0]['score']:.2f}. "
                "These are synthetic demo records. Human approval is required."
            )
        else:
            narrative = (
                f"Matching evaluated {evaluated} candidates and found "
                "no eligible processor."
            )

        return {
            "session_id": f"mock-{uuid.uuid4().hex[:12]}",
            "narrative": narrative,
            "top_matches": results,
            "proposed_pickup": None,
            "requires_approval": True,
            "mock": True,
        }

    # Call the actual deployed IBM watsonx Orchestrate agent.
    agent_result, run_id = _run_watsonx_agent(listing, listing_data)

    if agent_result.get("listing_id") != listing.id:
        raise HTTPException(
            502, "The agent returned results for a different listing."
        )

    # Check whether the agent snapshot agrees with the current API ranking.
    agent_matches = agent_result.get("top_matches", [])
    if isinstance(agent_matches, str):
        try:
            agent_matches = json.loads(agent_matches)
        except json.JSONDecodeError:
            agent_matches = []

    local_ids = [r["processor_id"] for r in results]
    agent_ids = [
        r.get("processor_id")
        for r in agent_matches
        if isinstance(r, dict)
    ]

    if not results:
        narrative = (
            f"The live WasteLoop AI Agent evaluated listing {listing.id}. "
            f"The API independently checked {evaluated} candidates and found "
            "no currently eligible processors."
        )
    else:
        narrative = (
            "The live WasteLoop AI Agent successfully called "
            "find_waste_matches. The API independently recomputed eligibility "
            f"and ranking against its current database. "
            f"It evaluated {evaluated} candidates. "
            f"The strongest verified match is {results[0]['processor_name']} "
            f"with a score of {results[0]['score']:.2f}."
        )

        suggested_date = agent_result.get("proposed_pickup_date")
        if suggested_date:
            try:
                pickup_date = date.fromisoformat(str(suggested_date))
                if listing_data.available_from <= pickup_date <= listing_data.available_until:
                    narrative += (
                        f" The agent suggested {pickup_date.isoformat()} "
                        "as a pickup date. This is a recommendation only."
                    )
            except ValueError:
                pass

        if agent_ids != local_ids:
            narrative += (
                " Note: the agent's synthetic snapshot differs from the "
                "current API database. The displayed matches use the "
                "API-verified ranking."
            )

    narrative += (
        " No pickup has been created or approved. "
        "A human must explicitly propose and approve any pickup."
    )

    return {
        "session_id": run_id,
        "narrative": narrative,
        "top_matches": results,
        "proposed_pickup": None,
        "requires_approval": True,
        "mock": False,
    }
