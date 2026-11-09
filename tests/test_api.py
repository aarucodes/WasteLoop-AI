from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.database import Base, get_db
from api import models
from api.main import app


@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    with TestingSession() as db:
        generator = models.Generator(
            name="Demo Generator", type=models.GeneratorType.APARTMENT,
            address="Whitefield, Bengaluru", pincode="560066", lat=12.97, lng=77.59,
            contact_email="demo@example.test", is_synthetic=True)
        processor = models.Processor(
            name="Demo Processor", processor_type=models.ProcessorType.BIOGAS_PLANT,
            address="Peenya, Bengaluru", pincode="560058", lat=12.97, lng=77.59,
            contact_email="processor@example.test", licence_number="SYNTH-LIC-001",
            is_synthetic=True)
        db.add_all([generator, processor]); db.flush()
        today = date.today()
        db.add(models.ProcessorCapacity(
            processor_id=processor.id, material_type=models.MaterialType.WET_ORGANIC,
            min_quantity_kg=50, max_quantity_kg=1000, accepted_grades="A,B",
            available_from=today - timedelta(days=1), available_until=today + timedelta(days=20),
            current_load_kg=100))
        listing = models.WasteListing(
            generator_id=generator.id, material_type=models.MaterialType.WET_ORGANIC,
            quantity_kg=200, quality_grade=models.QualityGrade.A,
            available_from=today, available_until=today + timedelta(days=7),
            description="Source-separated demo waste", status=models.ListingStatus.OPEN,
            is_synthetic=True)
        db.add(listing); db.commit()
        listing_id, processor_id = listing.id, processor.id
    with TestClient(app) as test_client:
        test_client.test_listing_id = listing_id
        test_client.test_processor_id = processor_id
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_health_and_matching(client):
    assert client.get("/health").json()["status"] == "ok"
    result = client.get(f"/matching/{client.test_listing_id}")
    assert result.status_code == 200
    body = result.json()
    assert len(body["top_matches"]) == 1
    assert body["top_matches"][0]["processor_id"] == client.test_processor_id


def test_pickup_requires_eligibility_and_starts_proposed(client):
    today = date.today().isoformat()
    bad = client.post("/pickups", json={"listing_id": client.test_listing_id,
        "processor_id": 999, "proposed_date": today})
    assert bad.status_code == 404
    good = client.post("/pickups", json={"listing_id": client.test_listing_id,
        "processor_id": client.test_processor_id, "proposed_date": today})
    assert good.status_code == 201
    assert good.json()["status"] == "PROPOSED"
    assert good.json()["approved_by"] is None


def test_only_human_action_can_approve_and_transitions_are_guarded(client):
    today = date.today().isoformat()
    made = client.post("/pickups", json={"listing_id": client.test_listing_id,
        "processor_id": client.test_processor_id, "proposed_date": today}).json()
    pid = made["id"]
    missing_actor = client.patch(f"/pickups/{pid}/status", json={"status": "APPROVED"})
    assert missing_actor.status_code == 422
    skipped = client.patch(f"/pickups/{pid}/status", json={"status": "COMPLETED"})
    assert skipped.status_code == 409
    approved = client.patch(f"/pickups/{pid}/status", json={
        "status": "APPROVED", "approved_by": "Demo Reviewer"})
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"
    assert approved.json()["approved_by"] == "Demo Reviewer"
    capacities = client.get("/processor-capacities").json()
    assert capacities[0]["current_load_kg"] == 300
    transit = client.patch(f"/pickups/{pid}/status", json={"status": "IN_TRANSIT"})
    assert transit.status_code == 200
    completed = client.patch(f"/pickups/{pid}/status", json={"status": "COMPLETED"})
    assert completed.status_code == 200
    assert completed.json()["status"] == "COMPLETED"
    capacities = client.get("/processor-capacities").json()
    assert capacities[0]["current_load_kg"] == 100


def test_client_cannot_inject_pickup_status(client):
    response = client.post("/pickups", json={"listing_id": client.test_listing_id,
        "processor_id": client.test_processor_id, "proposed_date": date.today().isoformat(),
        "status": "APPROVED", "approved_by": "attacker"})
    # Extra fields are rejected by the request schema.
    assert response.status_code == 422


def test_agent_mock_never_creates_a_pickup(client, monkeypatch):
    monkeypatch.setenv("USE_MOCK_AGENT", "true")
    response = client.post("/agent/match", json={"listing_id": client.test_listing_id})
    assert response.status_code == 200
    body = response.json()
    assert body["mock"] is True
    assert body["requires_approval"] is True
    assert body["proposed_pickup"] is None
    assert client.get("/pickups").json() == []


# ── Generator creation (POST /generators) ─────────────────────────────────────

VALID_GENERATOR = {
    "name": "Sunrise Apartments",
    "type": "APARTMENT",
    "address": "Whitefield Main Road, Bengaluru",
    "pincode": "560066",
    "lat": 12.9716,
    "lng": 77.7499,
    "contact_email": "rwa@sunriseapts.test",
    "is_synthetic": False,
}


def test_create_generator_returns_201_with_id(client):
    resp = client.post("/generators", json=VALID_GENERATOR)
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] > 0
    assert body["name"] == "Sunrise Apartments"
    assert body["type"] == "APARTMENT"
    assert body["pincode"] == "560066"
    assert body["is_synthetic"] is False


def test_created_generator_appears_in_list(client):
    client.post("/generators", json=VALID_GENERATOR)
    resp = client.get("/generators")
    assert resp.status_code == 200
    names = [g["name"] for g in resp.json()]
    assert "Sunrise Apartments" in names


def test_create_generator_all_types_accepted(client):
    """Every GeneratorType value must be accepted by POST /generators."""
    for gtype in ("APARTMENT", "IT_PARK", "COMMERCIAL", "HOSPITAL", "HOTEL"):
        payload = {**VALID_GENERATOR, "name": f"Gen {gtype}", "type": gtype,
                   "contact_email": f"{gtype.lower()}@test.test"}
        resp = client.post("/generators", json=payload)
        assert resp.status_code == 201, f"Failed for type={gtype}: {resp.text}"
        assert resp.json()["type"] == gtype


def test_create_generator_invalid_pincode_rejected(client):
    bad = {**VALID_GENERATOR, "pincode": "12345"}   # only 5 digits
    resp = client.post("/generators", json=bad)
    assert resp.status_code == 422

    bad2 = {**VALID_GENERATOR, "pincode": "ABCDEF"}  # non-numeric
    resp2 = client.post("/generators", json=bad2)
    assert resp2.status_code == 422


def test_create_generator_name_too_short_rejected(client):
    bad = {**VALID_GENERATOR, "name": "X"}  # min_length=2
    resp = client.post("/generators", json=bad)
    assert resp.status_code == 422


def test_create_generator_address_too_short_rejected(client):
    bad = {**VALID_GENERATOR, "address": "A"}  # min_length=5
    resp = client.post("/generators", json=bad)
    assert resp.status_code == 422


def test_create_generator_extra_fields_rejected(client):
    """GeneratorCreate uses extra='forbid'."""
    bad = {**VALID_GENERATOR, "unknown_field": "oops"}
    resp = client.post("/generators", json=bad)
    assert resp.status_code == 422


def test_create_generator_missing_required_field_rejected(client):
    for field in ("name", "type", "address", "pincode", "lat", "lng", "contact_email"):
        payload = {k: v for k, v in VALID_GENERATOR.items() if k != field}
        resp = client.post("/generators", json=payload)
        assert resp.status_code == 422, f"Expected 422 when '{field}' is missing"


def test_new_generator_id_used_for_waste_listing(client):
    """
    End-to-end: create a generator via POST /generators, then use its returned
    ID (not a hardcoded value) to create a waste listing.
    """
    gen_resp = client.post("/generators", json=VALID_GENERATOR)
    assert gen_resp.status_code == 201
    new_gen_id = gen_resp.json()["id"]

    today = date.today()
    listing_resp = client.post("/waste-listings", json={
        "generator_id": new_gen_id,
        "material_type": "WET_ORGANIC",
        "quantity_kg": 250.0,
        "quality_grade": "A",
        "available_from": today.isoformat(),
        "available_until": (today + timedelta(days=7)).isoformat(),
        "is_synthetic": False,
    })
    assert listing_resp.status_code == 201
    body = listing_resp.json()
    assert body["generator_id"] == new_gen_id
    assert body["status"] == "OPEN"


def test_waste_listing_with_unknown_generator_rejected(client):
    today = date.today()
    resp = client.post("/waste-listings", json={
        "generator_id": 99999,
        "material_type": "DRY_PAPER",
        "quantity_kg": 100.0,
        "quality_grade": "B",
        "available_from": today.isoformat(),
        "available_until": (today + timedelta(days=5)).isoformat(),
        "is_synthetic": False,
    })
    assert resp.status_code == 404
