"""
IBM Db2 Configuration Module for Saarthi
=========================================
Centralized configuration for IBM Db2 connection strings,
SSL settings, and connection parameters.
"""

import os
import urllib.parse
from pathlib import Path
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Load .env if present
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)


class Db2Config:
    """Configuration class for IBM Db2 connection management."""

    ENABLED: bool = os.getenv("USE_IBM_DB2", "false").lower() in ("true", "1", "yes")
    HOST: str = os.getenv("DB2_HOST", "localhost")
    PORT: int = int(os.getenv("DB2_PORT", "50000"))
    DATABASE: str = os.getenv("DB2_DATABASE", "BLUDB")
    USER: str = os.getenv("DB2_USER", "db2inst1")
    PASSWORD: str = os.getenv("DB2_PASSWORD", "")
    SECURITY: str = os.getenv("DB2_SECURITY", "")  # e.g. "SSL" or empty
    SCHEMA: str = os.getenv("DB2_SCHEMA", "SAARTHI")

    # Connection pooling parameters
    POOL_SIZE: int = int(os.getenv("DB2_POOL_SIZE", "5"))
    MAX_OVERFLOW: int = int(os.getenv("DB2_MAX_OVERFLOW", "10"))
    POOL_TIMEOUT: int = int(os.getenv("DB2_POOL_TIMEOUT", "30"))
    POOL_RECYCLE: int = int(os.getenv("DB2_POOL_RECYCLE", "1800"))

    @classmethod
    def is_configured(cls) -> bool:
        """Check if minimum required credentials for Db2 are provided."""
        return bool(cls.USER and cls.PASSWORD and cls.HOST and cls.DATABASE)

    @classmethod
    def get_sqlalchemy_uri(cls) -> str:
        """
        Construct SQLAlchemy URI for ibm_db_sa dialect.
        Format: ibm_db_sa://{user}:{password}@{host}:{port}/{database}
        """
        encoded_user = urllib.parse.quote_plus(cls.USER)
        encoded_pass = urllib.parse.quote_plus(cls.PASSWORD)
        
        uri = f"ibm_db_sa://{encoded_user}:{encoded_pass}@{cls.HOST}:{cls.PORT}/{cls.DATABASE}"
        
        # Add SSL security parameter if configured
        if cls.SECURITY.upper() == "SSL":
            uri += ";SECURITY=SSL;"
            
        return uri

    @classmethod
    def get_driver_connect_args(cls) -> Dict[str, Any]:
        """Extra connection args for native ibm_db driver."""
        args: Dict[str, Any] = {
            "autocommit": False
        }
        if cls.SECURITY.upper() == "SSL":
            args["SECURITY"] = "SSL"
        return args

    @classmethod
    def summary(cls) -> Dict[str, Any]:
        """Return a safe summary of configuration without exposing credentials."""
        return {
            "enabled": cls.ENABLED,
            "is_configured": cls.is_configured(),
            "host": cls.HOST,
            "port": cls.PORT,
            "database": cls.DATABASE,
            "user": cls.USER,
            "schema": cls.SCHEMA,
            "security": cls.SECURITY or "PLAINTEXT"
        }

