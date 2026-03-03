# SQLite data schema

This folder holds SQLite databases used by the PBM Deep Research app.

## `knowledge.db` (PBM claims – used by agent and Django admin)

Table: **pbm_claims** (NCPDP-style synthetic pharmacy claims from PBM perspective)

| Column                | Type    | Description                    |
|-----------------------|---------|--------------------------------|
| id                    | INTEGER | Primary key                    |
| claim_id              | TEXT    | Claim identifier               |
| transaction_id        | TEXT    | Transaction id                 |
| claim_status          | TEXT    | Approved / Rejected / Reversed |
| patient_id            | TEXT    | Patient id                     |
| age_group             | TEXT    | e.g. 18-34, 65+                |
| region                | TEXT    | Geographic region              |
| plan_id               | TEXT    | Payer plan                     |
| group_id              | TEXT    | Group id                       |
| drug_name            | TEXT    | e.g. Osimertinib               |
| ndc_code              | TEXT    | NDC code                       |
| therapeutic_class     | TEXT    | e.g. EGFR TKI                  |
| specialty_drug_flag   | INTEGER | 1 = specialty                  |
| diagnosis_code        | TEXT    | ICD-10                         |
| disease_category      | TEXT    | e.g. NSCLC                     |
| ingredient_cost       | REAL    | Drug cost                      |
| dispensing_fee        | REAL    | Dispensing fee                 |
| copay                 | REAL    | Patient copay                  |
| plan_paid_amount      | REAL    | Plan paid                      |
| rebate_estimate       | REAL    | Rebate estimate                |
| quantity              | INTEGER | Quantity dispensed             |
| days_supply           | INTEGER | Days supply                    |
| refill_number         | INTEGER | Refill number                  |
| pharmacy_id           | TEXT    | Pharmacy id                   |
| pharmacy_type         | TEXT    | Retail / Specialty / Mail etc. |
| prescriber_id         | TEXT    | Prescriber id                  |
| fill_date             | TEXT    | Fill date (ISO)                |
| adjudication_time     | TEXT    | Adjudication timestamp         |

Populate/refresh: `python populate_pbm_claims.py`

## `chat.db` (Chat UI sessions – used by `db.py`)

- **sessions**: id (TEXT), created_at (TEXT), last_message (TEXT)
- **messages**: id (INTEGER), session_id (TEXT), role (TEXT), content (TEXT), created_at (TEXT)
