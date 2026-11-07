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
