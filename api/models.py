"""
SQLAlchemy ORM models for WasteLoop AI.

Every model that holds user-originated data includes an `is_synthetic` column.
All rows seeded from CSV files have is_synthetic=True, making it unambiguous
which records are demonstration data vs real registrations.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from api.database import Base


# ── Enumerations ──────────────────────────────────────────────────────────────

class GeneratorType(str, enum.Enum):
    APARTMENT    = "APARTMENT"
    IT_PARK      = "IT_PARK"
    COMMERCIAL   = "COMMERCIAL"
    HOSPITAL     = "HOSPITAL"
    HOTEL        = "HOTEL"


class MaterialType(str, enum.Enum):
    WET_ORGANIC  = "WET_ORGANIC"
    DRY_PAPER    = "DRY_PAPER"
    DRY_PLASTIC  = "DRY_PLASTIC"
    DRY_METAL    = "DRY_METAL"
    E_WASTE      = "E_WASTE"
    GLASS        = "GLASS"
    MIXED        = "MIXED"


class QualityGrade(str, enum.Enum):
    A = "A"   # Clean / source-separated
    B = "B"   # Minor contamination
    C = "C"   # Mixed / contaminated


class ListingStatus(str, enum.Enum):
    OPEN               = "OPEN"
    MATCHED            = "MATCHED"
    PICKUP_SCHEDULED   = "PICKUP_SCHEDULED"
    COMPLETED          = "COMPLETED"
    CANCELLED          = "CANCELLED"


class ProcessorType(str, enum.Enum):
    BIOGAS_PLANT       = "BIOGAS_PLANT"
    COMPOST_FACILITY   = "COMPOST_FACILITY"
    PAPER_RECYCLER     = "PAPER_RECYCLER"
    PLASTIC_RECYCLER   = "PLASTIC_RECYCLER"
    METAL_RECYCLER     = "METAL_RECYCLER"
    E_WASTE_HANDLER    = "E_WASTE_HANDLER"
    GLASS_RECYCLER     = "GLASS_RECYCLER"


class RecommendedBy(str, enum.Enum):
    SYSTEM = "SYSTEM"
    AGENT  = "AGENT"


class PickupStatus(str, enum.Enum):
    PROPOSED   = "PROPOSED"
    APPROVED   = "APPROVED"
    IN_TRANSIT = "IN_TRANSIT"
    COMPLETED  = "COMPLETED"
    CANCELLED  = "CANCELLED"


# ── Models ────────────────────────────────────────────────────────────────────

class Generator(Base):
    """Bulk waste producer: apartment complex, IT park, commercial establishment."""
    __tablename__ = "generators"

    id             = Column(Integer, primary_key=True, index=True)
    name           = Column(String(200), nullable=False)
    type           = Column(Enum(GeneratorType), nullable=False)
    address        = Column(Text, nullable=False)
    pincode        = Column(String(10), nullable=False)
    lat            = Column(Float, nullable=False)
    lng            = Column(Float, nullable=False)
    contact_email  = Column(String(200), nullable=False)
    registered_at  = Column(DateTime, server_default=func.now(), nullable=False)
    is_synthetic   = Column(Boolean, default=False, nullable=False)

    waste_listings = relationship("WasteListing", back_populates="generator")


class WasteListing(Base):
    """A single waste disposal requirement posted by a generator."""
    __tablename__ = "waste_listings"

    id               = Column(Integer, primary_key=True, index=True)
    generator_id     = Column(Integer, ForeignKey("generators.id"), nullable=False)
    material_type    = Column(Enum(MaterialType), nullable=False)
    quantity_kg      = Column(Float, nullable=False)
    quality_grade    = Column(Enum(QualityGrade), nullable=False)
    available_from   = Column(Date, nullable=False)
    available_until  = Column(Date, nullable=False)
    description      = Column(Text, nullable=True)
    status           = Column(Enum(ListingStatus), default=ListingStatus.OPEN, nullable=False)
    created_at       = Column(DateTime, server_default=func.now(), nullable=False)
    is_synthetic     = Column(Boolean, default=False, nullable=False)

    generator        = relationship("Generator", back_populates="waste_listings")
    matches          = relationship("Match", back_populates="listing")
    pickups          = relationship("Pickup", back_populates="listing")


class Processor(Base):
    """Authorised waste processing facility."""
    __tablename__ = "processors"

    id               = Column(Integer, primary_key=True, index=True)
    name             = Column(String(200), nullable=False)
    processor_type   = Column(Enum(ProcessorType), nullable=False)
    address          = Column(Text, nullable=False)
    pincode          = Column(String(10), nullable=False)
    lat              = Column(Float, nullable=False)
    lng              = Column(Float, nullable=False)
    contact_email    = Column(String(200), nullable=False)
    licence_number   = Column(String(100), nullable=False)
    registered_at    = Column(DateTime, server_default=func.now(), nullable=False)
    is_synthetic     = Column(Boolean, default=False, nullable=False)

    capacities       = relationship("ProcessorCapacity", back_populates="processor")
    matches          = relationship("Match", back_populates="processor")
    pickups          = relationship("Pickup", back_populates="processor")


class ProcessorCapacity(Base):
    """
    A single material-type capacity window for a processor.
    One processor may have multiple rows (one per material type they accept).
    """
    __tablename__ = "processor_capacity"

    id                 = Column(Integer, primary_key=True, index=True)
    processor_id       = Column(Integer, ForeignKey("processors.id"), nullable=False)
    material_type      = Column(Enum(MaterialType), nullable=False)
    min_quantity_kg    = Column(Float, nullable=False)
    max_quantity_kg    = Column(Float, nullable=False)
    # Comma-separated quality grades accepted, e.g. "A,B"
    accepted_grades    = Column(String(10), nullable=False)
    available_from     = Column(Date, nullable=False)
    available_until    = Column(Date, nullable=False)
    # Current committed load in kg (sum of APPROVED/IN_TRANSIT pickups)
    current_load_kg    = Column(Float, default=0.0, nullable=False)

    processor          = relationship("Processor", back_populates="capacities")


class Match(Base):
    """
    A scored pairing of a WasteListing with a Processor.
    score_breakdown is stored as a JSON string.
    recommended_by distinguishes system-generated from agent-generated matches.
    """
    __tablename__ = "matches"

    id               = Column(Integer, primary_key=True, index=True)
    listing_id       = Column(Integer, ForeignKey("waste_listings.id"), nullable=False)
    processor_id     = Column(Integer, ForeignKey("processors.id"), nullable=False)
    score            = Column(Float, nullable=False)
    # JSON string: {"material_score":1.0, "quantity_score":0.9, ...}
    score_breakdown  = Column(Text, nullable=False)
    explanation      = Column(Text, nullable=False)
    recommended_by   = Column(Enum(RecommendedBy), default=RecommendedBy.SYSTEM, nullable=False)
    created_at       = Column(DateTime, server_default=func.now(), nullable=False)

    listing          = relationship("WasteListing", back_populates="matches")
    processor        = relationship("Processor", back_populates="matches")
    pickup           = relationship("Pickup", back_populates="match", uselist=False)


class Pickup(Base):
    """
    A proposed or active waste-collection event.

    State machine:
      PROPOSED → APPROVED (human action only) → IN_TRANSIT → COMPLETED
                                               → CANCELLED (from any state)

    The agent may create a PROPOSED record but CANNOT advance it to APPROVED.
    Only an authorised Streamlit action calling PATCH /pickups/{id}/status
    can move status from PROPOSED to APPROVED.
    """
    __tablename__ = "pickups"

    id               = Column(Integer, primary_key=True, index=True)
    match_id         = Column(Integer, ForeignKey("matches.id"), nullable=True)
    listing_id       = Column(Integer, ForeignKey("waste_listings.id"), nullable=False)
    processor_id     = Column(Integer, ForeignKey("processors.id"), nullable=False)
    proposed_date    = Column(Date, nullable=False)
    approved_by      = Column(String(200), nullable=True)   # email / username of approver
    approved_at      = Column(DateTime, nullable=True)
    status           = Column(Enum(PickupStatus), default=PickupStatus.PROPOSED, nullable=False)
    # Estimated CO₂ saved (kg) — populated only after COMPLETED, never fabricated
    co2_kg_saved     = Column(Float, nullable=True)
    notes            = Column(Text, nullable=True)
    created_at       = Column(DateTime, server_default=func.now(), nullable=False)

    match            = relationship("Match", back_populates="pickup")
    listing          = relationship("WasteListing", back_populates="pickups")
    processor        = relationship("Processor", back_populates="pickups")
