"""
scripts/seed_db.py
------------------
Loads synthetic demonstration data from data/*.csv into the database.

Usage:
    python scripts/seed_db.py              # seed if tables are empty
    python scripts/seed_db.py --force      # drop and recreate all rows

All seeded rows have is_synthetic=True.  The --force flag is safe to run
repeatedly during development; it only touches rows where is_synthetic=True.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

# Make the project root importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
from sqlalchemy.orm import Session

from api.database import SessionLocal, init_db
from api.models import (
    Generator,
    GeneratorType,
    Match,
    Pickup,
    MaterialType,
    Processor,
    ProcessorCapacity,
    ProcessorType,
    QualityGrade,
    WasteListing,
    ListingStatus,
)

DATA_DIR = ROOT / "data"


def _parse_date(val: str) -> date:
    return date.fromisoformat(str(val))


def seed_generators(db: Session) -> dict:
    """
    Insert generators from CSV.
    Returns a mapping of CSV id -> DB id.
    """
    df = pd.read_csv(DATA_DIR / "generators.csv")
    id_map = {}
    for _, row in df.iterrows():
        g = Generator(
            name=row["name"],
            type=GeneratorType(row["type"]),
            address=row["address"],
            pincode=str(row["pincode"]),
            lat=float(row["lat"]),
            lng=float(row["lng"]),
            contact_email=row["contact_email"],
            is_synthetic=True,
        )
        db.add(g)
        db.flush()
        id_map[int(row["id"])] = g.id
    print(f"  [OK] {len(id_map)} generators seeded")
    return id_map


def seed_processors(db: Session) -> dict:
    df = pd.read_csv(DATA_DIR / "processors.csv")
    id_map = {}
    for _, row in df.iterrows():
        p = Processor(
            name=row["name"],
            processor_type=ProcessorType(row["processor_type"]),
            address=row["address"],
            pincode=str(row["pincode"]),
            lat=float(row["lat"]),
            lng=float(row["lng"]),
            contact_email=row["contact_email"],
            licence_number=row["licence_number"],
            is_synthetic=True,
        )
        db.add(p)
        db.flush()
        id_map[int(row["id"])] = p.id
    print(f"  [OK] {len(id_map)} processors seeded")
    return id_map


def seed_processor_capacity(db: Session, processor_id_map: dict) -> None:
    df = pd.read_csv(DATA_DIR / "processor_capacity.csv")
    count = 0
    for _, row in df.iterrows():
        csv_proc_id = int(row["processor_id"])
        db_proc_id = processor_id_map.get(csv_proc_id)
        if db_proc_id is None:
            print(f"  [WARN] Skipping capacity row: processor CSV id {csv_proc_id} not found")
            continue
        cap = ProcessorCapacity(
            processor_id=db_proc_id,
            material_type=MaterialType(row["material_type"]),
            min_quantity_kg=float(row["min_quantity_kg"]),
            max_quantity_kg=float(row["max_quantity_kg"]),
            accepted_grades=row["accepted_grades"],
            available_from=_parse_date(row["available_from"]),
            available_until=_parse_date(row["available_until"]),
            current_load_kg=float(row["current_load_kg"]),
        )
        db.add(cap)
        count += 1
    print(f"  [OK] {count} processor capacity rows seeded")


def seed_waste_listings(db: Session, generator_id_map: dict) -> None:
    df = pd.read_csv(DATA_DIR / "waste_listings.csv")
    count = 0
    for _, row in df.iterrows():
        csv_gen_id = int(row["generator_id"])
        db_gen_id = generator_id_map.get(csv_gen_id)
        if db_gen_id is None:
            print(f"  [WARN] Skipping listing row: generator CSV id {csv_gen_id} not found")
            continue
        listing = WasteListing(
            generator_id=db_gen_id,
            material_type=MaterialType(row["material_type"]),
            quantity_kg=float(row["quantity_kg"]),
            quality_grade=QualityGrade(row["quality_grade"]),
            available_from=_parse_date(row["available_from"]),
            available_until=_parse_date(row["available_until"]),
            description=row["description"] if pd.notna(row.get("description")) else None,
            status=ListingStatus.OPEN,
            is_synthetic=True,
        )
        db.add(listing)
        count += 1
    print(f"  [OK] {count} waste listings seeded")


def clear_synthetic_data(db: Session) -> None:
    """Remove all rows flagged is_synthetic=True (safe for --force re-seed).

    ProcessorCapacity, Match and Pickup rows do not carry is_synthetic, so they
    are removed by tracing them to synthetic parent listings/processors first.
    """
    # Remove dependent workflow rows first; they do not carry is_synthetic.
    synthetic_listing_ids = db.query(WasteListing.id).filter(WasteListing.is_synthetic == True)
    synthetic_processor_ids = db.query(Processor.id).filter(Processor.is_synthetic == True)
    pickup_deleted = db.query(Pickup).filter(
        (Pickup.listing_id.in_(synthetic_listing_ids)) |
        (Pickup.processor_id.in_(synthetic_processor_ids))
    ).delete(synchronize_session="fetch")
    match_deleted = db.query(Match).filter(
        (Match.listing_id.in_(synthetic_listing_ids)) |
        (Match.processor_id.in_(synthetic_processor_ids))
    ).delete(synchronize_session="fetch")
    print(f"  [DEL] Cleared {pickup_deleted} synthetic pickups and {match_deleted} synthetic matches")

    # Delete dependent capacity rows before processors.
    cap_deleted = (
        db.query(ProcessorCapacity)
        .filter(
            ProcessorCapacity.processor_id.in_(
                db.query(Processor.id).filter(Processor.is_synthetic == True)
            )
        )
        .delete(synchronize_session="fetch")
    )
    print(f"  [DEL] Cleared {cap_deleted} synthetic rows from processor_capacity")

    for model in [WasteListing, Generator, Processor]:
        deleted = db.query(model).filter(model.is_synthetic == True).delete()
        print(f"  [DEL] Cleared {deleted} synthetic rows from {model.__tablename__}")


def run(force: bool = False) -> None:
    init_db()
    db = SessionLocal()
    try:
        gen_count = db.query(Generator).filter(Generator.is_synthetic == True).count()
        if gen_count > 0 and not force:
            print(
                f"Database already contains {gen_count} synthetic generator(s). "
                "Use --force to reseed."
            )
            return

        if force:
            clear_synthetic_data(db)
            db.commit()

        print("Seeding synthetic demonstration data...")
        gen_id_map = seed_generators(db)
        proc_id_map = seed_processors(db)
        seed_processor_capacity(db, proc_id_map)
        seed_waste_listings(db, gen_id_map)
        db.commit()
        print("Seeding complete.")
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed WasteLoop demo data")
    parser.add_argument("--force", action="store_true",
                        help="Clear existing synthetic rows before seeding")
    args = parser.parse_args()
    run(force=args.force)