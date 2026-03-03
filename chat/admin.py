from django.contrib import admin

from .models import PBMClaim


@admin.register(PBMClaim)
class PBMClaimAdmin(admin.ModelAdmin):
    list_display = (
        "claim_id",
        "drug_name",
        "claim_status",
        "fill_date",
        "ingredient_cost",
        "plan_paid_amount",
        "region",
        "pharmacy_type",
    )
    list_filter = ("claim_status", "drug_name", "region", "pharmacy_type", "age_group")
    search_fields = (
        "claim_id",
        "transaction_id",
        "patient_id",
        "drug_name",
        "ndc_code",
        "diagnosis_code",
        "prescriber_id",
        "pharmacy_id",
    )
    readonly_fields = (
        "claim_id",
        "transaction_id",
        "claim_status",
        "patient_id",
        "age_group",
        "region",
        "plan_id",
        "group_id",
        "drug_name",
        "ndc_code",
        "therapeutic_class",
        "specialty_drug_flag",
        "diagnosis_code",
        "disease_category",
        "ingredient_cost",
        "dispensing_fee",
        "copay",
        "plan_paid_amount",
        "rebate_estimate",
        "quantity",
        "days_supply",
        "refill_number",
        "pharmacy_id",
        "pharmacy_type",
        "prescriber_id",
        "fill_date",
        "adjudication_time",
    )
    ordering = ("-fill_date", "claim_id")
    list_per_page = 50
