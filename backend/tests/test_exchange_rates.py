import pytest
from unittest.mock import patch, MagicMock
from urllib.error import URLError
from app.services.exchange_rates import NBKExchangeRatesService

MOCK_XML_DATA = """<?xml version="1.0" encoding="utf-8"?>
<rates>
  <item>
    <title>USD</title>
    <description>460.0</description>
    <quant>1</quant>
  </item>
  <item>
    <title>EUR</title>
    <description>490.0</description>
    <quant>1</quant>
  </item>
  <item>
    <title>RUB</title>
    <description>5.2</description>
    <quant>1</quant>
  </item>
  <item>
    <title>CNY</title>
    <description>64.0</description>
    <quant>1</quant>
  </item>
</rates>
""".encode("utf-8")


def test_nbk_exchange_rates_fetching_mocked():
    # Force cache clear
    NBKExchangeRatesService._cache = {}
    NBKExchangeRatesService._cache_date = None
    # Mock urllib.request.urlopen
    mock_response = MagicMock()
    mock_response.read.return_value = MOCK_XML_DATA
    mock_response.__enter__.return_value = mock_response
    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        rates = NBKExchangeRatesService.fetch_rates()
        # Verify mocked data was parsed correctly
        assert "KZT" in rates
        assert rates["KZT"] == 1.0
        assert rates["USD"] == 460.0
        assert rates["EUR"] == 490.0
        assert rates["RUB"] == 5.2
        assert rates["CNY"] == 64.0
        # Verify the urlopen was called with correct parameters
        mock_urlopen.assert_called_once()
        # Check individual fetch
        usd_rate = NBKExchangeRatesService.get_rate("USD")
        assert usd_rate == 460.0


def test_nbk_exchange_rates_failure_fallback():
    # Force cache clear
    NBKExchangeRatesService._cache = {}
    NBKExchangeRatesService._cache_date = None
    # Mock urlopen to raise an exception
    with patch(
        "urllib.request.urlopen", side_effect=URLError("Network connection failed")
    ):
        # Act: should not crash, but fallback to hardcoded minimal values
        rates = NBKExchangeRatesService.fetch_rates()
        # Assert fallback rates are active and reasonable
        assert "KZT" in rates
        assert rates["KZT"] == 1.0
        assert rates["USD"] == 450.0  # From hardcoded fallbacks
        assert rates["EUR"] == 485.0
    # Non-existent currency raises error
    with pytest.raises(ValueError):
        NBKExchangeRatesService.get_rate("XYZ_NON_EXISTENT")
