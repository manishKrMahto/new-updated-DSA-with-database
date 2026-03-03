"""
Initialize the SQLite knowledge database for the Hybrid RAG retriever.

This script:
- Reads `data/synthetic_claims_120.csv`
- Creates `data/knowledge.db`
- Creates a `claims` table with typed columns
- Loads all rows from the CSV into the table

Run once (or whenever you want to reset the DB):

    python init_knowledge_db.py
"""

import sqlite3
from pathlib import Path

import pandas as pd

from settings import DATA_DIR, KNOWLEDGE_DB_PATH


CSV_PATH = DATA_DIR / "synthetic_claims_120.csv"


def init_knowledge_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not CSV_PATH.exists():
        raise FileNotFoundError(f"CSV not found at {CSV_PATH}")

    df = pd.read_csv(CSV_PATH)

    # Normalize / enforce dtypes
    df["claim_id"] = df["claim_id"].astype(str)
    df["patient_id"] = df["patient_id"].astype(str)
    df["drug_name"] = df["drug_name"].astype(str)
    df["diagnosis"] = df["diagnosis"].astype(str)
    df["quantity"] = df["quantity"].astype(int)
    df["days_supply"] = df["days_supply"].astype(int)
    df["ingredient_cost"] = df["ingredient_cost"].astype(float)
    df["fill_date"] = pd.to_datetime(df["fill_date"]).dt.date.astype(str)

    # Create / overwrite SQLite DB
    if KNOWLEDGE_DB_PATH.exists():
        KNOWLEDGE_DB_PATH.unlink()

    conn = sqlite3.connect(str(KNOWLEDGE_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE claims (
                claim_id TEXT PRIMARY KEY,
                patient_id TEXT NOT NULL,
                drug_name TEXT NOT NULL,
                diagnosis TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                days_supply INTEGER NOT NULL,
                ingredient_cost REAL NOT NULL,
                fill_date TEXT NOT NULL
            )
            """
        )

        # Bulk insert using executemany for efficiency
        rows = [
            (
                r.claim_id,
                r.patient_id,
                r.drug_name,
                r.diagnosis,
                int(r.quantity),
                int(r.days_supply),
                float(r.ingredient_cost),
                str(r.fill_date),
            )
            for r in df.itertuples(index=False)
        ]
        cur.executemany(
            """
            INSERT INTO claims (
                claim_id,
                patient_id,
                drug_name,
                diagnosis,
                quantity,
                days_supply,
                ingredient_cost,
                fill_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
        print(f"Initialized knowledge DB at {KNOWLEDGE_DB_PATH} with {len(rows)} rows in 'claims'.")
    finally:
        conn.close()


if __name__ == "__main__":
    init_knowledge_db()

