import logging
from typing import List, Optional
from sqlalchemy.orm import Session
from app.core.models import BrokerRegistry, TROISRegistry

logger = logging.getLogger(__name__)


class KGDRegistryService:
    """
    Search and management services for:
    - Licensed customs brokers (KGD RK registry).
    - Trademark intellectual property protections (TROIS).
    """

    @staticmethod
    def search_brokers(
        db: Session, city: Optional[str] = None, query: Optional[str] = None
    ) -> List[BrokerRegistry]:
        """
        Search licensed brokers in the SQLite database by city and name.
        """
        q = db.query(BrokerRegistry)
        if city:
            q = q.filter(BrokerRegistry.city.ilike(f"%{city}%"))
        if query:
            q = q.filter(
                (BrokerRegistry.company_name.ilike(f"%{query}%"))
                | (BrokerRegistry.license_number.ilike(f"%{query}%"))
            )
        return q.all()

    @staticmethod
    def check_trois_trademark(db: Session, query_name: str) -> Optional[TROISRegistry]:
        """
        Check if a given product name matches any registered protected trademark in the TROIS registry.
        """
        # Exact match or wildcard match
        trademark = (
            db.query(TROISRegistry)
            .filter(TROISRegistry.trademark_name.ilike(f"%{query_name}%"))
            .first()
        )
        return trademark

    @staticmethod
    def seed_initial_brokers(db: Session):
        """
        Populate DB with initial sample brokers of major Kazakhstan cities if empty.
        """
        if db.query(BrokerRegistry).count() > 0:
            return

        sample_brokers = [
            BrokerRegistry(
                license_number="001/2024",
                company_name="Кеден-Сервис Алматы",
                bin_number="120440056123",
                city="Алматы",
                address="пр. Райымбека, 451",
                contacts="+7 (727) 333-22-11, info@kedenservice.kz",
                rating=4.9,
            ),
            BrokerRegistry(
                license_number="002/2024",
                company_name="Астана-Customs Логистик",
                bin_number="150640098341",
                city="Астана",
                address="ул. Кунаева, 12/1",
                contacts="+7 (7172) 44-55-66, astana@customs.kz",
                rating=4.8,
            ),
            BrokerRegistry(
                license_number="003/2024",
                company_name="Каспи-Брокер Сервис",
                bin_number="180940023412",
                city="Актау",
                address="Морской порт, офис 22",
                contacts="+7 (7292) 50-60-70, aktau@caspi-broker.kz",
                rating=4.7,
            ),
        ]
        db.add_all(sample_brokers)
        db.commit()
        logger.info("Successfully seeded initial sample brokers into database")
