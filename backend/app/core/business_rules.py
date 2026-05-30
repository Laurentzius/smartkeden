"""
Immutable business rules for Kazakhstan customs calculations and document
generation.  Changing a rule here changes it across the entire system —
calculation engine, document generator, API responses, and eventually the
frontend via the /api/business-rules endpoint.
"""

from pydantic import BaseModel, Field


class BusinessRules(BaseModel):
    """Single source of truth for customs business constants.

    All fields are read-only after construction.  Tests can instantiate
    alternative instances and inject them via the seams on CustomsCalculator
    and DocumentGenerator.
    """

    # ---- Tax rates --------------------------------------------------------
    import_vat_rate: float = Field(
        default=0.16,
        ge=0.0,
        le=1.0,
        description="Import VAT rate (НДС на импорт) — 16 % in RK (2026)",
    )

    # ---- Fixed fees -------------------------------------------------------
    customs_processing_fee_kzt: float = Field(
        default=20_000.0,
        ge=0.0,
        description="Fixed customs processing fee in KZT (таможенный сбор)",
    )

    # ---- Document generation defaults -------------------------------------
    default_invoice_prefix: str = Field(
        default="INV-2026",
        description="Invoice number prefix for generated commercial invoices",
    )
    default_contract_prefix: str = Field(
        default="KED-2026",
        description="Contract number prefix for generated documents",
    )
    default_seller_address: str = Field(
        default=(
            "Industrial District, Nanshan, Shenzhen, Guangdong, China\n"
            "Tax ID: 91440300MA5EXXXX"
        ),
        description="Default seller address for commercial invoices",
    )
    default_buyer_address: str = Field(
        default=(
            "Республика Казахстан, г. Алматы, Медеуский р-н, пр. Достык, 120\n"
            "БИН: 120440056123, Тел: +7 (727) 333-22-11"
        ),
        description="Default buyer address for commercial invoices",
    )

    model_config = {"frozen": True}


# Singleton — import this everywhere.
rules = BusinessRules()
