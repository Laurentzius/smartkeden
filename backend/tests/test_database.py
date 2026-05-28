from app.core.database import SessionLocal, Base, engine
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
