from app.core.database import SessionLocal, Base, engine
from app.core.models import BrokerRegistry
from app.services.kgd_registry import KGDRegistryService

def test_database_and_broker_seeding():
    # Arrange & Act
    db = SessionLocal()
    try:
        # Seed brokers (should already be done by startup, but let's test manually)
        KGDRegistryService.seed_initial_brokers(db)
        
        # Search brokers in Almaty
        almaty_brokers = KGDRegistryService.search_brokers(db, city="Алматы")
        
        # Assert
        assert len(almaty_brokers) > 0
        assert almaty_brokers[0].company_name == "Кеден-Сервис Алматы"
        assert almaty_brokers[0].city == "Алматы"
        assert almaty_brokers[0].rating == 4.9
        
        # Search brokers in Astana
        astana_brokers = KGDRegistryService.search_brokers(db, city="Астана")
        assert len(astana_brokers) > 0
        assert astana_brokers[0].company_name == "Астана-Customs Логистик"
        
        # Search with text query
        search_res = KGDRegistryService.search_brokers(db, query="Каспи")
        assert len(search_res) > 0
        assert "Каспи" in search_res[0].company_name
        
    finally:
        db.close()


def test_database_seed_is_idempotent():
    """Repeated seeding should NOT create duplicate broker entries."""
    db = SessionLocal()
    try:
        # Ensure clean slate by deleting all brokers
        db.query(BrokerRegistry).delete()
        db.commit()
        
        # First seed
        KGDRegistryService.seed_initial_brokers(db)
        count_after_first = db.query(BrokerRegistry).count()
        assert count_after_first == 3

        # Second seed (should be idempotent, not create duplicates)
        KGDRegistryService.seed_initial_brokers(db)
        count_after_second = db.query(BrokerRegistry).count()
        assert count_after_second == 3
        
    finally:
        db.close()


def test_database_search_sql_injection_resistant():
    """Search should handle SQL-like characters without breaking or injecting."""
    db = SessionLocal()
    try:
        KGDRegistryService.seed_initial_brokers(db)
        
        # SQL injection attempts should return empty results safely
        res_drop = KGDRegistryService.search_brokers(db, query="'; DROP TABLE")
        assert len(res_drop) == 0
        
        res_union = KGDRegistryService.search_brokers(db, query="' UNION SELECT")
        assert len(res_union) == 0
        
        res_comment = KGDRegistryService.search_brokers(db, query="--")
        assert len(res_comment) == 0
        
        # Verify table still exists and has data after injection attempts
        assert db.query(BrokerRegistry).count() == 3
        
    finally:
        db.close()


def test_database_search_combined_city_and_query():
    """Search with both city and query should apply both filters."""
    db = SessionLocal()
    try:
        KGDRegistryService.seed_initial_brokers(db)
        
        # Search in Almaty by company name fragment
        res = KGDRegistryService.search_brokers(db, city="Алматы", query="Кеден")
        assert len(res) == 1
        assert res[0].company_name == "Кеден-Сервис Алматы"
        
        # Search in Astana by company name fragment
        res_astana = KGDRegistryService.search_brokers(db, city="Астана", query="Customs")
        assert len(res_astana) == 1
        assert res_astana[0].company_name == "Астана-Customs Логистик"
        
        # Combined filters with no match
        res_empty = KGDRegistryService.search_brokers(db, city="Алматы", query="Астана")
        assert len(res_empty) == 0
        
    finally:
        db.close()


def test_database_search_by_license_number():
    """Search by license_number fragment should return matching brokers."""
    db = SessionLocal()
    try:
        KGDRegistryService.seed_initial_brokers(db)
        
        res = KGDRegistryService.search_brokers(db, query="001/2024")
        assert len(res) == 1
        assert res[0].license_number == "001/2024"
        
        res_all = KGDRegistryService.search_brokers(db, query="/2024")
        assert len(res_all) == 3  # All have /2024 in license
        
    finally:
        db.close()


def test_database_empty_broker_registry():
    """Empty broker registry should return empty results gracefully."""
    db = SessionLocal()
    try:
        # Clear all brokers
        db.query(BrokerRegistry).delete()
        db.commit()
        
        res = KGDRegistryService.search_brokers(db, city="Алматы")
        assert len(res) == 0
        
        res_query = KGDRegistryService.search_brokers(db, query="Каспи")
        assert len(res_query) == 0
        
    finally:
        db.close()
