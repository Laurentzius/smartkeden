import pytest
from app.services.exchange_rates import NBKExchangeRatesService

def test_nbk_exchange_rates_caching():
    # Fetch rates (will execute live fetch or use mock/fallbacks if network is down)
    rates = NBKExchangeRatesService.fetch_rates()
    
    assert "KZT" in rates
    assert rates["KZT"] == 1.0
    
    # We should have main foreign currencies
    assert "USD" in rates
    assert "EUR" in rates
    assert "RUB" in rates
    assert "CNY" in rates
    
    # Assert values are reasonable (> 0)
    assert rates["USD"] > 100.0
    assert rates["CNY"] > 10.0
    
    # Check individual fetch
    usd_rate = NBKExchangeRatesService.get_rate("USD")
    assert usd_rate == rates["USD"]
    
    # Non-existent currency raises error
    with pytest.raises(ValueError):
        NBKExchangeRatesService.get_rate("XYZ_NON_EXISTENT")
