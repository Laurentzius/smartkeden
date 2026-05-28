import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

class NBKExchangeRatesService:
    """
    Service to fetch daily official exchange rates from the National Bank of Kazakhstan (НБРК).
    Rates feed URL: https://www.nationalbank.kz/rss/rates_all.xml
    """
    _cache: Dict[str, float] = {}
    _cache_date: Optional[str] = None

    @classmethod
    def fetch_rates(cls) -> Dict[str, float]:
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        # Return cached rates if they are fetched today
        if cls._cache_date == today_str and cls._cache:
            return cls._cache

        url = "https://www.nationalbank.kz/rss/rates_all.xml"
        try:
            logger.info("Fetching daily exchange rates from National Bank of Kazakhstan")
            req = urllib.request.Request(
                url, 
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                xml_data = response.read()
                
            root = ET.fromstring(xml_data)
            rates = {"KZT": 1.0} # Base currency
            
            for item in root.findall(".//item"):
                title = item.find("title")
                description = item.find("description")
                quant = item.find("quant")
                
                if title is not None and description is not None:
                    currency_code = title.text.strip().upper()
                    try:
                        rate_val = float(description.text.strip())
                        # Handle quantity (e.g. 100 JPY or 100 RUB)
                        quantity = float(quant.text.strip()) if quant is not None and quant.text else 1.0
                        
                        rates[currency_code] = rate_val / quantity
                    except ValueError:
                        continue
            
            cls._cache = rates
            cls._cache_date = today_str
            logger.info(f"Successfully loaded and cached {len(rates)} rates from NBK")
            return rates
            
        except Exception as e:
            logger.error(f"Failed to fetch exchange rates from NBK: {e}")
            # Return fallback/stale rates if available, otherwise minimal fallbacks
            if cls._cache:
                return cls._cache
            # Hardcoded minimal fallback estimates (approximate values)
            return {
                "KZT": 1.0,
                "USD": 450.0,
                "EUR": 485.0,
                "RUB": 5.0,
                "CNY": 62.0,
            }

    @classmethod
    def get_rate(cls, currency: str) -> float:
        rates = cls.fetch_rates()
        code = currency.upper().strip()
        if code not in rates:
            raise ValueError(f"Currency code '{currency}' not supported or found in NBK rates")
        return rates[code]
