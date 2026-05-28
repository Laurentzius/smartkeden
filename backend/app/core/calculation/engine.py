from abc import ABC, abstractmethod
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional, List

class ExchangeRateProvider(ABC):
    """Seam for exchange rate resolution."""
    @abstractmethod
    def get_rate(self, currency: str) -> float:
        pass

class NBKExchangeRateProvider(ExchangeRateProvider):
    """Concrete adapter resolving rates via official NBK service."""
    def get_rate(self, currency: str) -> float:
        from app.services.exchange_rates import NBKExchangeRatesService
        return NBKExchangeRatesService.get_rate(currency)

class MCIRegistry(ABC):
    """Seam for MCI (МРП) value resolution by date/year."""
    @abstractmethod
    def get_mci(self, year: int) -> float:
        pass

class StaticMCIRegistry(MCIRegistry):
    """Concrete adapter with historical and current MCI rates in RK."""
    def get_mci(self, year: int) -> float:
        mci_table = {
            2026: 3692.0,
            2025: 3692.0,
            2024: 3692.0,
            2023: 3450.0,
            2022: 3063.0,
        }
        return mci_table.get(year, 3692.0)

class CalculationRequest(BaseModel):
    invoice_price: float = Field(..., description="Invoice price in foreign currency or KZT")
    currency: str = Field("USD", description="Three-letter currency code (USD, EUR, RUB, etc.)")
    exchange_rate: Optional[float] = Field(None, description="Optional exchange rate; auto-resolved if omitted")
    transport_to_border: float = Field(0.0, description="Transport cost to the EAEU/RK border in KZT")
    duty_rate_percent: float = Field(0.0, description="Ad-valorem duty rate in percent (e.g., 10.0 for 10%)")
    excise_rate_percent: float = Field(0.0, description="Ad-valorem excise rate in percent")
    excise_specific_rate: float = Field(0.0, description="Specific excise rate (KZT per unit)")
    excise_units_count: float = Field(0.0, description="Quantity of units subject to specific excise")
    is_subject_to_recycling_fee: bool = Field(False, description="Whether the product is subject to recycling fee (утильсбор)")
    recycling_fee_base_mci: float = Field(0.0, description="Base MCI (МРП) multiplier for recycling fee")
    mci_value: Optional[float] = Field(None, description="Optional MCI value in KZT; auto-resolved if omitted")
    declaration_date: Optional[str] = Field(None, description="Optional declaration date (YYYY-MM-DD) for historical rates")

class CalculationResponse(BaseModel):
    customs_value_kzt: float = Field(..., description="Customs value in KZT (Таможенная стоимость)")
    customs_fee_kzt: float = Field(..., description="Customs clearance fee (Таможенный сбор)")
    customs_duty_kzt: float = Field(..., description="Import/export customs duty (Таможенная пошлина)")
    excise_tax_kzt: float = Field(..., description="Excise tax amount (Акциз)")
    vat_base_kzt: float = Field(..., description="VAT Calculation Base (База НДС)")
    import_vat_kzt: float = Field(..., description="Import VAT amount (12% of VAT Base)")
    recycling_fee_kzt: float = Field(..., description="Recycling fee amount (Утильсбор)")
    total_payments_kzt: float = Field(..., description="Total payments to be paid (Итого к уплате)")

class CustomsCalculator:
    _rate_provider: ExchangeRateProvider = NBKExchangeRateProvider()
    _mci_registry: MCIRegistry = StaticMCIRegistry()

    @classmethod
    def set_rate_provider(cls, provider: ExchangeRateProvider):
        """Inject rate provider adapter at the seam."""
        cls._rate_provider = provider

    @classmethod
    def set_mci_registry(cls, registry: MCIRegistry):
        """Inject MCI registry adapter at the seam."""
        cls._mci_registry = registry

    @classmethod
    def calculate(cls, req: CalculationRequest) -> CalculationResponse:
        # Resolve exchange rate if omitted
        rate = req.exchange_rate
        if rate is None:
            if req.currency.upper() == "KZT":
                rate = 1.0
            else:
                rate = cls._rate_provider.get_rate(req.currency)

        # Resolve declaration year and MCI value if omitted
        mci = req.mci_value
        if mci is None:
            year = 2026
            if req.declaration_date:
                try:
                    year = datetime.strptime(req.declaration_date, "%Y-%m-%d").year
                except ValueError:
                    pass
            mci = cls._mci_registry.get_mci(year)

        # 1. Customs Value (Таможенная стоимость)
        customs_value_kzt = (req.invoice_price * rate) + req.transport_to_border
        
        # 2. Customs Fee (Таможенный сбор)
        # Fixed processing fee under current RK regulations is 20,000 KZT
        customs_fee_kzt = 20000.0
        
        # 3. Customs Duty (Пошлина)
        customs_duty_kzt = customs_value_kzt * (req.duty_rate_percent / 100.0)
        
        # 4. Excise Tax (Акциз)
        # Ad-valorem excise + specific excise
        excise_ad_valorem = customs_value_kzt * (req.excise_rate_percent / 100.0)
        excise_specific = req.excise_specific_rate * req.excise_units_count
        excise_tax_kzt = excise_ad_valorem + excise_specific
        
        # 5. VAT Base (База НДС)
        # Formula: Customs Value + Customs Fee + Customs Duty + Excise
        vat_base_kzt = customs_value_kzt + customs_fee_kzt + customs_duty_kzt + excise_tax_kzt
        
        # 6. Import VAT (12%)
        import_vat_kzt = vat_base_kzt * 0.12
        
        # 7. Recycling Fee (Утильсбор)
        recycling_fee_kzt = 0.0
        if req.is_subject_to_recycling_fee:
            recycling_fee_kzt = req.recycling_fee_base_mci * mci
            
        # 8. Total Payments (Итого платежей)
        total_payments_kzt = (
            customs_fee_kzt +
            customs_duty_kzt +
            excise_tax_kzt +
            import_vat_kzt +
            recycling_fee_kzt
        )
        
        return CalculationResponse(
            customs_value_kzt=round(customs_value_kzt, 2),
            customs_fee_kzt=round(customs_fee_kzt, 2),
            customs_duty_kzt=round(customs_duty_kzt, 2),
            excise_tax_kzt=round(excise_tax_kzt, 2),
            vat_base_kzt=round(vat_base_kzt, 2),
            import_vat_kzt=round(import_vat_kzt, 2),
            recycling_fee_kzt=round(recycling_fee_kzt, 2),
            total_payments_kzt=round(total_payments_kzt, 2),
        )