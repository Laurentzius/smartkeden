from app.core.calculation.engine import CustomsCalculator, CalculationRequest
from app.core.business_rules import rules


def test_customs_calculation_standard():
    # Arrange
    req = CalculationRequest(
        invoice_price=1000.0,  # $1,000
        currency="USD",
        exchange_rate=450.0,  # 450 KZT/USD -> 450,000 KZT customs value
        transport_to_border=50000.0,  # 50,000 KZT
        duty_rate_percent=10.0,  # 10% customs duty
        excise_rate_percent=5.0,  # 5% excise
        excise_specific_rate=0.0,
        excise_units_count=0.0,
        is_subject_to_recycling_fee=False,
    )

    # Act
    res = CustomsCalculator.calculate(req)

    # Assert
    # Customs Value = 1000 * 450 + 50,000 = 500,000 KZT
    assert res.customs_value_kzt == 500000.0

    # Customs Fee = rules.customs_processing_fee_kzt
    assert res.customs_fee_kzt == rules.customs_processing_fee_kzt

    # Customs Duty = 500,000 * 10% = 50,000 KZT
    assert res.customs_duty_kzt == 50000.0

    # Excise = 500,000 * 5% = 25,000 KZT
    assert res.excise_tax_kzt == 25000.0

    # VAT Base = 500,000 (CV) + 20,000 (Fee) + 50,000 (Duty) + 25,000 (Excise) = 595,000 KZT
    assert res.vat_base_kzt == 595000.0

    # Import VAT = vat_base * rules.import_vat_rate
    assert res.import_vat_kzt == 595000.0 * rules.import_vat_rate

    # Total Payments = 20,000 (Fee) + 50,000 (Duty) + 25,000 (Excise) + 95,200 (VAT @16%) = 190,200 KZT
    assert res.total_payments_kzt == 190200.0


def test_customs_calculation_auto_resolve_exchange_rate():
    from app.core.calculation.engine import ExchangeRateProvider

    class MockRateProvider(ExchangeRateProvider):
        def get_rate(self, currency: str) -> float:
            return 500.0 if currency == "EUR" else 450.0

    # Inject mock rate provider
    CustomsCalculator.set_rate_provider(MockRateProvider())

    # Arrange: omit exchange_rate
    req = CalculationRequest(
        invoice_price=1000.0,
        currency="EUR",
        transport_to_border=0.0,
        duty_rate_percent=10.0,
    )

    # Act
    res = CustomsCalculator.calculate(req)

    # Assert: customs value should use EUR rate 500.0
    # Customs Value = 1000 * 500 = 500,000 KZT
    assert res.customs_value_kzt == 500000.0

    # Reset rate provider to default
    from app.core.calculation.engine import NBKExchangeRateProvider

    CustomsCalculator.set_rate_provider(NBKExchangeRateProvider())


def test_customs_calculation_auto_resolve_mci():
    # Arrange: omit mci_value and supply historical declaration_date (2023)
    req = CalculationRequest(
        invoice_price=1000.0,
        currency="KZT",  # No currency exchange needed
        transport_to_border=0.0,
        is_subject_to_recycling_fee=True,
        recycling_fee_base_mci=50.0,
        declaration_date="2023-06-15",
    )
    # Act
    res = CustomsCalculator.calculate(req)
    # Assert: 2023 MCI was 3450 KZT
    # Recycling fee = 50 * 3450 = 172,500 KZT
    assert res.recycling_fee_kzt == 172500.0


def test_customs_calculation_edge_cases():
    # 1. Zero invoice price
    req_zero = CalculationRequest(
        invoice_price=0.0,
        currency="USD",
        exchange_rate=450.0,
        transport_to_border=50000.0,
        duty_rate_percent=10.0,
    )
    res_zero = CustomsCalculator.calculate(req_zero)
    assert res_zero.customs_value_kzt == 50000.0  # Just transport
    assert res_zero.customs_duty_kzt == 5000.0
    assert res_zero.total_payments_kzt == rules.customs_processing_fee_kzt + 5000.0 + (
        (50000 + rules.customs_processing_fee_kzt + 5000) * rules.import_vat_rate
    )
    # 2. Duty rate 0%
    req_no_duty = CalculationRequest(
        invoice_price=1000.0,
        currency="KZT",
        exchange_rate=1.0,
        transport_to_border=10000.0,
        duty_rate_percent=0.0,
    )
    res_no_duty = CustomsCalculator.calculate(req_no_duty)
    assert (
        res_no_duty.import_vat_kzt
        == (11000.0 + rules.customs_processing_fee_kzt) * rules.import_vat_rate
    )
    # 3. High duty rate (150%)
    req_high_duty = CalculationRequest(
        invoice_price=1000.0,
        currency="KZT",
        exchange_rate=1.0,
        transport_to_border=0.0,
        duty_rate_percent=150.0,
    )
    res_high_duty = CustomsCalculator.calculate(req_high_duty)
    assert res_high_duty.customs_duty_kzt == 1500.0
    # 4. Specific excise with zero count vs non-zero count
    req_excise = CalculationRequest(
        invoice_price=1000.0,
        currency="KZT",
        exchange_rate=1.0,
        transport_to_border=0.0,
        excise_specific_rate=500.0,
        excise_units_count=10.0,
    )
    res_excise = CustomsCalculator.calculate(req_excise)
    assert res_excise.excise_tax_kzt == 5000.0  # 500 * 10
