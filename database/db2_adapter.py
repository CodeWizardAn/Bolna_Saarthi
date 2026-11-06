"""
IBM Db2 Adapter & Integration Layer for Saarthi
================================================
Provides:
- Db2 Engine initialization and connection pooling
- Health-check and connectivity validation
- LangChain SQLDatabase toolkit connector for agents
- Automatic catalog seeding from local JSON to Db2
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
from sqlalchemy.engine import Engine

try:
    from .db2_config import Db2Config
    from .models import Base, Product
except ImportError:
    from db2_config import Db2Config
    from models import Base, Product

logger = logging.getLogger(__name__)

# Check driver availability
IBM_DB_AVAILABLE = False
IBM_DB_SA_AVAILABLE = False

try:
    import ibm_db
    IBM_DB_AVAILABLE = True
except ImportError:
    logger.warning("ibm_db driver not installed. Install with `pip install ibm_db`.")

try:
    import ibm_db_sa
    IBM_DB_SA_AVAILABLE = True
except ImportError:
    logger.warning("ibm_db_sa dialect not installed. Install with `pip install ibm_db_sa`.")


class Db2Adapter:
    """Enterprise Adapter managing connections and LangChain toolkits for IBM Db2."""

    _instance: Optional["Db2Adapter"] = None
    _engine: Optional[Engine] = None
    _session_factory: Optional[sessionmaker] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._engine is not None:
            return
        self.config = Db2Config
        if self.config.is_configured():
            self._init_engine()

    def _init_engine(self):
        """Create SQLAlchemy engine with QueuePool configured for IBM Db2."""
        try:
            uri = self.config.get_sqlalchemy_uri()
            self._engine = create_engine(
                uri,
                poolclass=QueuePool,
                pool_size=self.config.POOL_SIZE,
                max_overflow=self.config.MAX_OVERFLOW,
                pool_timeout=self.config.POOL_TIMEOUT,
                pool_recycle=self.config.POOL_RECYCLE,
                pool_pre_ping=True
            )
            self._session_factory = sessionmaker(bind=self._engine, autoflush=False, autocommit=False)
            logger.info(f"✅ IBM Db2 SQLAlchemy Engine initialized: {self.config.HOST}:{self.config.PORT}/{self.config.DATABASE}")
        except Exception as e:
            logger.error(f"Failed to initialize IBM Db2 engine: {e}")
            self._engine = None

    @property
    def engine(self) -> Optional[Engine]:
        return self._engine

    def get_session(self) -> Optional[Session]:
        """Obtain a session connected to IBM Db2."""
        if not self._session_factory:
            if self.config.is_configured():
                self._init_engine()
            else:
                return None
        return self._session_factory() if self._session_factory else None

    def test_connection(self) -> Dict[str, Any]:
        """Verify live connectivity to IBM Db2 database."""
        if not IBM_DB_AVAILABLE or not IBM_DB_SA_AVAILABLE:
            return {
                "status": "error",
                "message": "IBM Db2 driver or SQLAlchemy dialect not installed.",
                "drivers": {"ibm_db": IBM_DB_AVAILABLE, "ibm_db_sa": IBM_DB_SA_AVAILABLE}
            }

        if not self.config.is_configured():
            return {
                "status": "unconfigured",
                "message": "Db2 credentials missing in environment. Set DB2_HOST, DB2_PORT, DB2_DATABASE, DB2_USER, DB2_PASSWORD.",
                "config": self.config.summary()
            }

        try:
            if not self._engine:
                self._init_engine()

            with self._engine.connect() as conn:
                # Query IBM Db2 system catalog / dual table
                result = conn.execute(text("SELECT CURRENT TIMESTAMP, CURRENT SERVER FROM SYSIBM.SYSDUMMY1")).fetchone()
                return {
                    "status": "connected",
                    "server_timestamp": str(result[0]) if result else None,
                    "server_name": str(result[1]) if result else None,
                    "database": self.config.DATABASE,
                    "host": self.config.HOST
                }
        except Exception as e:
            logger.error(f"Db2 connection test failed: {e}")
            return {
                "status": "failed",
                "error": str(e),
                "config": self.config.summary()
            }

    def create_tables(self):
        """Create Saarthi relational schema in IBM Db2."""
        if not self._engine:
            raise RuntimeError("Db2 engine not initialized.")
        Base.metadata.create_all(self._engine)
        logger.info("✅ Saarthi tables successfully verified/created in IBM Db2.")

    def get_langchain_db(self, include_tables: Optional[List[str]] = None):
        """
        Produce a LangChain SQLDatabase wrapper for use with LangChain agents
        and SQLDatabaseToolkit.
        """
        try:
            from langchain_community.utilities import SQLDatabase
        except ImportError:
            logger.warning("langchain-community not installed. Install with `pip install langchain-community`.")
            return None

        if not self._engine:
            self._init_engine()

        if not self._engine:
            raise RuntimeError("Cannot construct LangChain Db2 wrapper: Db2 engine not configured.")

        tables = include_tables or ["products", "rfps", "rfp_requirements", "product_matches", "bids", "audit_trail"]
        
        return SQLDatabase(
            engine=self._engine,
            include_tables=tables,
            sample_rows_in_table_info=2
        )

    def seed_catalog_from_json(self, json_path: Optional[str] = None) -> int:
        """
        Import 650+ verified OEM SKUs from local catalog JSON into IBM Db2.
        """
        if not json_path:
            json_path = Path(__file__).parent / "db_products" / "product_catalog.json"
        else:
            json_path = Path(json_path)

        if not json_path.exists():
            logger.warning(f"Catalog file not found at {json_path}")
            return 0

        session = self.get_session()
        if not session:
            logger.error("Could not obtain Db2 session for seeding.")
            return 0

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            products = data if isinstance(data, list) else data.get("products", [])
            count = 0

            for item in products:
                # Check for existing SKU
                sku = item.get("sku") or item.get("part_number") or item.get("id")
                if not sku:
                    continue
                
                existing = session.query(Product).filter_by(sku=str(sku)).first()
                if not existing:
                    prod = Product(
                        sku=str(sku),
                        name=item.get("name", "OEM Product"),
                        category=item.get("category", "Cables & Wires"),
                        manufacturer=item.get("manufacturer") or item.get("brand", "Generic OEM"),
                        specifications=item.get("specifications", item),
                        base_price=float(item.get("base_price") or item.get("price") or 0.0),
                        status="active"
                    )
                    session.add(prod)
                    count += 1

            session.commit()
            logger.info(f"✅ Seeded {count} OEM SKUs into IBM Db2.")
            return count
        except Exception as e:
            session.rollback()
            logger.error(f"Error seeding catalog into Db2: {e}")
            return 0
        finally:
            session.close()


# Module-level singleton helper
db2_adapter = Db2Adapter()


if __name__ == "__main__":
    import sys
    print("=" * 60)
    print("🚀 Saarthi IBM Db2 Integration Diagnostics")
    print("=" * 60)
    print(f"• Driver ibm_db available:     {'✅ Yes' if IBM_DB_AVAILABLE else '❌ No'}")
    print(f"• Dialect ibm_db_sa available: {'✅ Yes' if IBM_DB_SA_AVAILABLE else '❌ No'}")
    print("• Current Configuration:")
    for k, v in Db2Config.summary().items():
        print(f"   - {k}: {v}")
    
    print("-" * 60)
    print("• Testing live connection...")
    res = db2_adapter.test_connection()
    print(f"   Status: {res.get('status')}")
    print(f"   Message: {res.get('message', res.get('error', 'Ready'))}")
    print("=" * 60)

