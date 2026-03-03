"""
Utility script to create and populate a synthetic PBM NCPDP-style
claims dataset in the knowledge SQLite database.

The table is designed from the PBM analyst perspective and focuses on:
- NSCLC oncology specialty drugs (e.g., Osimertinib, Gefitinib, Erlotinib)
- Financial fields needed for cost and utilization analytics
- Attributes useful for fraud detection and prior-authorization reasoning
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import List, Tuple

import sqlite3

from settings import KNOWLEDGE_DB_PATH


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(KNOWLEDGE_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    """
    Create a PBM-focused synthetic claims table if it does not exist.

    Columns follow the requested minimum PBM perspective:
      - Claim identity, patient, drug, clinical, financial, utilization,
        network, and time dimensions.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pbm_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id TEXT NOT NULL,
            transaction_id TEXT NOT NULL,
            claim_status TEXT NOT NULL,

            patient_id TEXT NOT NULL,
            age_group TEXT NOT NULL,
            region TEXT NOT NULL,

            plan_id TEXT NOT NULL,
            group_id TEXT NOT NULL,

            drug_name TEXT NOT NULL,
            ndc_code TEXT NOT NULL,
            therapeutic_class TEXT NOT NULL,
            specialty_drug_flag INTEGER NOT NULL, -- 1 = specialty, 0 = non-specialty

            diagnosis_code TEXT NOT NULL,
            disease_category TEXT NOT NULL,

            ingredient_cost REAL NOT NULL,
            dispensing_fee REAL NOT NULL,
            copay REAL NOT NULL,
            plan_paid_amount REAL NOT NULL,
            rebate_estimate REAL NOT NULL,

            quantity INTEGER NOT NULL,
            days_supply INTEGER NOT NULL,
            refill_number INTEGER NOT NULL,

            pharmacy_id TEXT NOT NULL,
            pharmacy_type TEXT NOT NULL,
            prescriber_id TEXT NOT NULL,

            fill_date TEXT NOT NULL,
            adjudication_time TEXT NOT NULL
        )
        """
    )
    conn.commit()


def generate_synthetic_claims(num_rows: int = 50000) -> List[Tuple]:
    """
    Generate a synthetic PBM claims dataset.

    Theme:
      - NSCLC oncology specialty drugs (EGFR TKIs)
      - Focused on realistic ranges for cost and utilization
    """
    random.seed(42)

    drugs = [
        {
            "drug_name": "Osimertinib",
            "ndc_code": "00002-8215-01",
            "therapeutic_class": "EGFR TKI",
            "specialty": 1,
            "base_cost": 15000.0,
        },
        {
            "drug_name": "Gefitinib",
            "ndc_code": "0310-0650-60",
            "therapeutic_class": "EGFR TKI",
            "specialty": 1,
            "base_cost": 12000.0,
        },
        {
            "drug_name": "Erlotinib",
            "ndc_code": "50242-060-62",
            "therapeutic_class": "EGFR TKI",
            "specialty": 1,
            "base_cost": 11000.0,
        },
    ]

    age_groups = ["18-34", "35-49", "50-64", "65+"]
    regions = ["Northeast", "Midwest", "South", "West"]
    plans = ["COMMERCIAL", "MEDICARE", "MEDICAID", "EXCHANGE"]
    groups = ["GRP-A", "GRP-B", "GRP-C", "GRP-D", "GRP-E"]

    diagnosis_codes = [
        "C34.90",  # Malignant neoplasm of unspecified part of unspecified bronchus or lung
        "C34.10",
        "C34.30",
        "C34.80",
    ]
    disease_category = "NSCLC"

    statuses = ["Approved", "Rejected", "Reversed"]
    pharmacy_types = ["Retail", "Specialty", "Mail Order", "Hospital Outpatient"]

    base_fill_date = datetime.utcnow() - timedelta(days=365)

    rows: List[Tuple] = []
    for i in range(1, num_rows + 1):
        drug = random.choice(drugs)
        age_group = random.choices(
            age_groups, weights=[0.05, 0.15, 0.40, 0.40], k=1
        )[0]
        region = random.choice(regions)
        plan_id = random.choices(plans, weights=[0.55, 0.25, 0.15, 0.05], k=1)[0]
        group_id = random.choice(groups)

        diag_code = random.choices(
            diagnosis_codes, weights=[0.6, 0.2, 0.15, 0.05], k=1
        )[0]

        quantity = random.choice([28, 30, 56, 60, 90])
        days_supply = random.choice([28, 30, 30, 30, 60, 90])
        refill_number = random.choices([0, 1, 2, 3, 4], weights=[0.4, 0.3, 0.15, 0.1, 0.05], k=1)[0]

        base_cost = drug["base_cost"]
        ingredient_cost = round(
            base_cost * random.uniform(0.9, 1.15) * (days_supply / 30.0), 2
        )
        dispensing_fee = round(random.uniform(0.0, 80.0), 2)

        # Simple tiered copay model
        if plan_id == "MEDICARE":
            copay = round(random.uniform(0.0, 600.0), 2)
        elif plan_id == "MEDICAID":
            copay = round(random.uniform(0.0, 50.0), 2)
        else:
            copay = round(random.uniform(50.0, 500.0), 2)

        rebate_estimate = round(ingredient_cost * random.uniform(0.1, 0.35), 2)
        plan_paid_amount = round(
            max(ingredient_cost + dispensing_fee - copay - rebate_estimate, 0.0), 2
        )

        # Skew toward approved claims, but include some rejects/reversals
        claim_status = random.choices(
            statuses, weights=[0.88, 0.07, 0.05], k=1
        )[0]

        # IDs and network attributes
        claim_id = f"C{i:07d}"
        transaction_id = f"T{i:07d}-{random.randint(1000, 9999)}"
        patient_id = f"P{random.randint(10000, 99999)}"
        pharmacy_id = f"PH{random.randint(100, 999)}"
        prescriber_id = f"DR{random.randint(1000, 9999)}"
        pharmacy_type = random.choices(
            pharmacy_types, weights=[0.45, 0.35, 0.15, 0.05], k=1
        )[0]

        # Time: random day in the last 12 months
        fill_offset_days = random.randint(0, 364)
        fill_dt = base_fill_date + timedelta(days=fill_offset_days)
        # Adjudication within same day, a few minutes after fill
        adjudication_dt = fill_dt + timedelta(
            minutes=random.randint(1, 8 * 60)
        )

        fill_date_str = fill_dt.date().isoformat()
        adjudication_time_str = adjudication_dt.isoformat(timespec="seconds")

        row = (
            claim_id,
            transaction_id,
            claim_status,
            patient_id,
            age_group,
            region,
            plan_id,
            group_id,
            drug["drug_name"],
            drug["ndc_code"],
            drug["therapeutic_class"],
            int(drug["specialty"]),
            diag_code,
            disease_category,
            ingredient_cost,
            dispensing_fee,
            copay,
            plan_paid_amount,
            rebate_estimate,
            quantity,
            days_supply,
            refill_number,
            pharmacy_id,
            pharmacy_type,
            prescriber_id,
            fill_date_str,
            adjudication_time_str,
        )
        rows.append(row)

    return rows


def populate_pbm_claims(num_rows: int = 50000, truncate_first: bool = True) -> None:
    """
    Create the schema (if needed) and insert synthetic PBM claims.

    Args:
        num_rows: Target number of synthetic rows (10k–100k is reasonable).
        truncate_first: If True, clears existing rows from pbm_claims before insert.
    """
    conn = _get_connection()
    try:
        create_schema(conn)
        if truncate_first:
            conn.execute("DELETE FROM pbm_claims")
            conn.commit()

        rows = generate_synthetic_claims(num_rows=num_rows)
        conn.executemany(
            """
            INSERT INTO pbm_claims (
                claim_id,
                transaction_id,
                claim_status,
                patient_id,
                age_group,
                region,
                plan_id,
                group_id,
                drug_name,
                ndc_code,
                therapeutic_class,
                specialty_drug_flag,
                diagnosis_code,
                disease_category,
                ingredient_cost,
                dispensing_fee,
                copay,
                plan_paid_amount,
                rebate_estimate,
                quantity,
                days_supply,
                refill_number,
                pharmacy_id,
                pharmacy_type,
                prescriber_id,
                fill_date,
                adjudication_time
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            rows,
        )
        conn.commit()
        print(f"Inserted {len(rows)} synthetic PBM claims into pbm_claims table.")
    finally:
        conn.close()


if __name__ == "__main__":
    # Default to 50k rows; adjust as needed.
    populate_pbm_claims(num_rows=50000, truncate_first=True)

