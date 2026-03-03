"""
Django models for the chat app.

PBMClaim is an unmanaged model that maps to the existing pbm_claims table
in the knowledge database (data/knowledge.db), so it can be used in admin
and by the PBM agent.
"""

from django.db import models


class PBMClaim(models.Model):
    """
    Synthetic PBM NCPDP-style claim (read-only in admin).
    Table lives in the knowledge database; managed by populate_pbm_claims.py.
    """

    id = models.AutoField(primary_key=True)
    claim_id = models.CharField(max_length=32)
    transaction_id = models.CharField(max_length=64)
    claim_status = models.CharField(max_length=32)

    patient_id = models.CharField(max_length=32)
    age_group = models.CharField(max_length=16)
    region = models.CharField(max_length=64)

    plan_id = models.CharField(max_length=32)
    group_id = models.CharField(max_length=32)

    drug_name = models.CharField(max_length=128)
    ndc_code = models.CharField(max_length=32)
    therapeutic_class = models.CharField(max_length=64)
    specialty_drug_flag = models.IntegerField()

    diagnosis_code = models.CharField(max_length=32)
    disease_category = models.CharField(max_length=64)

    ingredient_cost = models.DecimalField(max_digits=12, decimal_places=2)
    dispensing_fee = models.DecimalField(max_digits=10, decimal_places=2)
    copay = models.DecimalField(max_digits=10, decimal_places=2)
    plan_paid_amount = models.DecimalField(max_digits=12, decimal_places=2)
    rebate_estimate = models.DecimalField(max_digits=12, decimal_places=2)

    quantity = models.IntegerField()
    days_supply = models.IntegerField()
    refill_number = models.IntegerField()

    pharmacy_id = models.CharField(max_length=32)
    pharmacy_type = models.CharField(max_length=64)
    prescriber_id = models.CharField(max_length=32)

    fill_date = models.CharField(max_length=16)
    adjudication_time = models.CharField(max_length=32)

    class Meta:
        managed = False
        db_table = "pbm_claims"
        verbose_name = "PBM Claim"
        verbose_name_plural = "PBM Claims"
        ordering = ["-fill_date", "claim_id"]
