"""
Storage service - spravuje životní cyklus SQLite DB na USB
"""
import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from typing import Optional
import asyncio

from backend.database import Base, get_db_path

class StorageService:
    def __init__(self):
        self.engine: Optional[object] = None
        self.SessionLocal: Optional[sessionmaker] = None
        self.available = False
        self.db_path: Optional[str] = None

    async def initialize(self):
        """Inicializace storage service - zkusí připojit DB pokud je USB dostupné"""
        import logging
        logger = logging.getLogger(__name__)
        
        db_path = get_db_path()
        logger.info(f"initialize called: db_path={db_path}, dir_exists={os.path.exists(os.path.dirname(db_path)) if db_path else False}")
        
        if db_path and os.path.exists(os.path.dirname(db_path)):
            try:
                await self._connect(db_path)
                logger.info(f"Database initialized successfully. available={self.available}")
            except Exception as e:
                logger.error(f"Failed to initialize DB: {e}", exc_info=True)
                self.available = False
        else:
            logger.warning(f"Cannot initialize DB: db_path={db_path}, dir_exists={os.path.exists(os.path.dirname(db_path)) if db_path else False}")

    async def _connect(self, db_path: str):
        """Připojí se k databázi"""
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"_connect called with db_path={db_path}")
        
        try:
            # SQLite s pool pro thread-safety
            self.db_path = db_path
            logger.info(f"Creating engine for {db_path}")
            self.engine = create_engine(
                f"sqlite:///{db_path}",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
                echo=False
            )
            logger.info("Engine created successfully")
            
            # Vytvoření tabulek
            logger.info("Creating/verifying tables")
            Base.metadata.create_all(bind=self.engine)
            logger.info("Tables created/verified")
            
            # Migrace - přidání error_message do scans pokud neexistuje
            await self._migrate_scans_error_message()
            # Migrace - přidání exclude_patterns do batches pokud neexistuje
            await self._migrate_batches_exclude_patterns()
            # Migrace - přidání enabled do batch_items pokud neexistuje
            await self._migrate_batch_items_enabled()
            # Migrace - přidání job_log do job_runs pokud neexistuje
            await self._migrate_job_runs_log()
            # Migrace - vytvoření job_file_statuses tabulky pokud neexistuje
            await self._migrate_job_file_statuses()
            logger.info("Migrations completed")
            
            logger.info("Creating SessionLocal")
            self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
            self.available = True
            logger.info(f"Database connection successful. available={self.available}, SessionLocal={self.SessionLocal is not None}, engine={self.engine is not None}")
        except Exception as e:
            logger.error(f"Error in _connect: {e}", exc_info=True)
            self.available = False
            self.SessionLocal = None
            self.engine = None
            raise
    
    async def _migrate_scans_error_message(self):
        """Migrace: přidá error_message sloupec do scans tabulky pokud neexistuje"""
        try:
            from sqlalchemy import text
            with self.engine.begin() as conn:
                # Zkontrolovat, zda sloupec existuje
                result = conn.execute(text("""
                    SELECT COUNT(*) FROM pragma_table_info('scans') WHERE name='error_message'
                """))
                count = result.scalar()
                
                if count == 0:
                    # Sloupec neexistuje, přidat ho
                    conn.execute(text("ALTER TABLE scans ADD COLUMN error_message TEXT"))
                    print("Migration: Added error_message column to scans table")
                else:
                    print("Migration: error_message column already exists")
        except Exception as e:
            print(f"Migration error: {e}")
            import traceback
            traceback.print_exc()
    
    async def _migrate_batches_exclude_patterns(self):
        """Migrace: přidá exclude_patterns sloupec do batches tabulky pokud neexistuje"""
        try:
            from sqlalchemy import text
            with self.engine.begin() as conn:
                # Zkontrolovat, zda sloupec existuje
                result = conn.execute(text("""
                    SELECT COUNT(*) FROM pragma_table_info('batches') WHERE name='exclude_patterns'
                """))
                count = result.scalar()
                
                if count == 0:
                    # Sloupec neexistuje, přidat ho
                    conn.execute(text("ALTER TABLE batches ADD COLUMN exclude_patterns JSON"))
                    print("Migration: Added exclude_patterns column to batches table")
                else:
                    print("Migration: exclude_patterns column already exists")
        except Exception as e:
            print(f"Migration error: {e}")
            import traceback
            traceback.print_exc()
    
    async def _migrate_batch_items_enabled(self):
        """Migrace: přidá enabled sloupec do batch_items tabulky pokud neexistuje"""
        try:
            from sqlalchemy import text
            with self.engine.begin() as conn:
                # Zkontrolovat, zda sloupec existuje
                result = conn.execute(text("""
                    SELECT COUNT(*) FROM pragma_table_info('batch_items') WHERE name='enabled'
                """))
                count = result.scalar()
                
                if count == 0:
                    # Sloupec neexistuje, přidat ho a nastavit všechny existující na True
                    conn.execute(text("ALTER TABLE batch_items ADD COLUMN enabled BOOLEAN DEFAULT 1"))
                    # Nastavit všechny existující záznamy na enabled=True
                    conn.execute(text("UPDATE batch_items SET enabled = 1 WHERE enabled IS NULL"))
                    print("Migration: Added enabled column to batch_items table")
                else:
                    print("Migration: enabled column already exists")
        except Exception as e:
            print(f"Migration error: {e}")
            import traceback
            traceback.print_exc()
    
    async def _migrate_job_runs_log(self):
        """Migrace: přidá job_log sloupec do job_runs tabulky pokud neexistuje"""
        try:
            from sqlalchemy import text
            with self.engine.begin() as conn:
                # Zkontrolovat, zda sloupec existuje
                result = conn.execute(text("""
                    SELECT COUNT(*) FROM pragma_table_info('job_runs') WHERE name='job_log'
                """))
                count = result.scalar()
                
                if count == 0:
                    # Sloupec neexistuje, přidat ho
                    conn.execute(text("ALTER TABLE job_runs ADD COLUMN job_log TEXT"))
                    print("Migration: Added job_log column to job_runs table")
                else:
                    print("Migration: job_log column already exists")
        except Exception as e:
            print(f"Migration error: {e}")
            import traceback
            traceback.print_exc()
    
    async def _disconnect(self):
        """Odpojí se od databáze"""
        if self.engine:
            self.engine.dispose()
            self.engine = None
            self.SessionLocal = None
        self.available = False
        self.db_path = None

    def get_session(self) -> Optional[Session]:
        """Vrátí DB session pokud je DB dostupná"""
        if not self.available or not self.SessionLocal:
            return None
        return self.SessionLocal()

    async def handle_available(self):
        """Zpracuje událost dostupnosti USB/DB"""
        import logging
        logger = logging.getLogger(__name__)
        
        if self.available:
            logger.info("Database already available, skipping connection")
            return
        
        db_path = get_db_path()
        logger.info(f"handle_available called: db_path={db_path}, dir_exists={os.path.exists(os.path.dirname(db_path)) if db_path else False}")
        
        if db_path and os.path.exists(os.path.dirname(db_path)):
            try:
                logger.info(f"Attempting to connect to database at {db_path}")
                await self._connect(db_path)
                logger.info(f"Successfully connected to database. available={self.available}, SessionLocal={self.SessionLocal is not None}")
            except Exception as e:
                logger.error(f"Failed to connect to DB: {e}", exc_info=True)
                self.available = False
        else:
            logger.warning(f"Cannot connect to DB: db_path={db_path}, dir_exists={os.path.exists(os.path.dirname(db_path)) if db_path else False}")

    async def handle_unavailable(self, reason: str):
        """Zpracuje událost nedostupnosti USB/DB"""
        if not self.available:
            return
        
        print(f"DB becoming unavailable: {reason}")
        await self._disconnect()

    async def cleanup(self):
        """Cleanup při ukončení aplikace"""
        await self._disconnect()

storage_service = StorageService()

