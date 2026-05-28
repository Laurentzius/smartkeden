from sqlalchemy import Column, Integer, String, Float, Boolean, Text, ForeignKey, DateTime
from sqlalchemy.sql import func
from app.core.database import Base

class HSCodeDirectory(Base):
    """EAEU 10-digit Harmonized System (HS) Codes Directory."""
    __tablename__ = "hs_code_directory"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(10), unique=True, index=True, nullable=False) # 10-digit code
    name_ru = Column(Text, nullable=False)
    name_kz = Column(Text, nullable=True)
    duty_rate_percent = Column(Float, default=0.0)
    excise_rate_percent = Column(Float, default=0.0)
    is_subject_to_recycling_fee = Column(Boolean, default=False)
    recycling_fee_base_mci = Column(Float, default=0.0) # multiplier of MCI
    non_tariff_requirements = Column(Text, nullable=True) # JSON or descriptive string (licenses, certificates)

class TROISRegistry(Base):
    """
    KGD RK register of Intellectual Property / Protected Trademarks (ТРОИС).
    Importers of these trademarks need special authorization.
    """
    __tablename__ = "trois_registry"

    id = Column(Integer, primary_key=True, index=True)
    trademark_name = Column(String(255), index=True, nullable=False)
    right_holder = Column(String(255), nullable=False)
    authorized_importers = Column(Text, nullable=True) # JSON list or text of allowed parties
    unauthorized_importers_action = Column(String(50), default="suspend") # suspend, reject, inspect
    registry_number = Column(String(100), unique=True, nullable=False)
    valid_until = Column(DateTime, nullable=True)

class BrokerRegistry(Base):
    """
    Customs brokers / declarant representatives licensed by KGD RK.
    """
    __tablename__ = "broker_registry"

    id = Column(Integer, primary_key=True, index=True)
    license_number = Column(String(100), unique=True, nullable=False)
    company_name = Column(String(255), index=True, nullable=False)
    bin_number = Column(String(12), unique=True, nullable=True) # Business Identification Number (БИН)
    city = Column(String(100), index=True, nullable=False)
    address = Column(Text, nullable=True)
    contacts = Column(String(255), nullable=True) # Phone numbers, emails
    rating = Column(Float, default=5.0)

class CalculationHistory(Base):
    """Saved historical calculations executed by users."""
    __tablename__ = "calculation_history"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(100), index=True, nullable=True)
    product_description = Column(Text, nullable=False)
    hs_code = Column(String(10), nullable=True)
    invoice_price = Column(Float, nullable=False)
    currency = Column(String(3), default="USD")
    exchange_rate = Column(Float, default=1.0)
    transport_to_border = Column(Float, default=0.0)
    total_customs_payments_kzt = Column(Float, nullable=False)
    calculated_at = Column(DateTime, server_default=func.now())
