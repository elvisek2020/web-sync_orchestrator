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
        logger.info(f"initialize called: db_path={db_path}, dir_exists={os.path.exists(os.path.dirname(db_path)) if db_path else False}, file_exists={os.path.exists(db_path) if db_path else False}")
        
        if db_path:
            # Zkontrolovat, zda adresář existuje (nebo vytvořit)
            db_dir = os.path.dirname(db_path)
            if not os.path.exists(db_dir):
                try:
                    os.makedirs(db_dir, exist_ok=True)
                    logger.info(f"Created database directory: {db_dir}")
                except Exception as e:
                    logger.error(f"Failed to create database directory: {e}", exc_info=True)
                    self.available = False
                    return
            
            try:
                await self._connect(db_path)
                logger.info(f"Database initialized successfully. available={self.available}, SessionLocal={self.SessionLocal is not None}, engine={self.engine is not None}")
            except Exception as e:
                logger.error(f"Failed to initialize DB: {e}", exc_info=True)
                self.available = False
                self.SessionLocal = None
                self.engine = None
        else:
            logger.warning(f"Cannot initialize DB: db_path is None")

    async def _connect(self, db_path: str):
        """Připojí se k databázi"""
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"_connect called with db_path={db_path}")
        
        # Nejdřív vytvořit engine a SessionLocal, pak provést migrace
        # To zajistí, že i když migrace selže, engine a SessionLocal budou nastaveny
        try:
            # SQLite s pool pro thread-safety
            self.db_path = db_path
            logger.info(f"Creating engine for {db_path}")
            self.engine = create_engine(
                f"sqlite:///{db_path}",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
                echo=False,
            )
            
            @event.listens_for(self.engine, "connect")
            def _set_sqlite_pragmas(dbapi_conn, connection_record):
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA busy_timeout=10000")
                cursor.close()
            logger.info("Engine created successfully")
            
            # Vytvoření tabulek
            logger.info("Creating/verifying tables")
            Base.metadata.create_all(bind=self.engine)
            logger.info("Tables created/verified")
            
            # Vytvořit SessionLocal PŘED migracemi, aby byl dostupný i když migrace selže
            logger.info("Creating SessionLocal")
            self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
            logger.info("SessionLocal created successfully")
            
            # Migrace - přidání error_message do scans pokud neexistuje
            try:
                await self._migrate_scans_error_message()
            except Exception as e:
                logger.warning(f"Migration _migrate_scans_error_message failed: {e}", exc_info=True)
            
            # Migrace - přidání exclude_patterns do batches pokud neexistuje
            try:
                await self._migrate_batches_exclude_patterns()
            except Exception as e:
                logger.warning(f"Migration _migrate_batches_exclude_patterns failed: {e}", exc_info=True)
            
            # Migrace - přidání enabled do batch_items pokud neexistuje
            try:
                await self._migrate_batch_items_enabled()
            except Exception as e:
                logger.warning(f"Migration _migrate_batch_items_enabled failed: {e}", exc_info=True)
            
            # Migrace - přidání error_message do batches pokud neexistuje
            try:
                await self._migrate_batches_error_message()
            except Exception as e:
                logger.warning(f"Migration _migrate_batches_error_message failed: {e}", exc_info=True)
            
            # Migrace - přidání job_log do job_runs pokud neexistuje
            try:
                await self._migrate_job_runs_log()
            except Exception as e:
                logger.warning(f"Migration _migrate_job_runs_log failed: {e}", exc_info=True)
            
            # Migrace - vytvoření job_file_statuses tabulky pokud neexistuje
            try:
                await self._migrate_job_file_statuses()
            except Exception as e:
                logger.warning(f"Migration _migrate_job_file_statuses failed: {e}", exc_info=True)
            
            # Migrace - přidání include_extra do batches pokud neexistuje
            try:
                await self._migrate_batches_include_extra()
            except Exception as e:
                logger.warning(f"Migration _migrate_batches_include_extra failed: {e}", exc_info=True)
            
            # Migrace - přidání error_message do diffs pokud neexistuje
            try:
                await self._migrate_diffs_error_message()
            except Exception as e:
                logger.warning(f"Migration _migrate_diffs_error_message failed: {e}", exc_info=True)
            
            logger.info("Migrations completed")
            
            self.available = True
            logger.info(f"Database connection successful. available={self.available}, SessionLocal={self.SessionLocal is not None}, engine={self.engine is not None}")
        except Exception as e:
            logger.error(f"Error in _connect: {e}", exc_info=True)
            # I při chybě zkusit zachovat engine a SessionLocal, pokud byly vytvořeny
            if self.engine is None or self.SessionLocal is None:
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
    
    async def _migrate_batches_error_message(self):
        """Migrace: přidá error_message sloupec do batches tabulky pokud neexistuje"""
        try:
            from sqlalchemy import text
            with self.engine.begin() as conn:
                # Zkontrolovat, zda sloupec existuje
                result = conn.execute(text("""
                    SELECT COUNT(*) FROM pragma_table_info('batches') WHERE name='error_message'
                """))
                count = result.scalar()
                
                if count == 0:
                    # Sloupec neexistuje, přidat ho
                    conn.execute(text("ALTER TABLE batches ADD COLUMN error_message TEXT"))
                    print("Migration: Added error_message column to batches table")
                else:
                    print("Migration: error_message column already exists")
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
    
    async def _migrate_job_file_statuses(self):
        """Migrace: vytvoří job_file_statuses tabulku pokud neexistuje"""
        try:
            from sqlalchemy import text, inspect
            inspector = inspect(self.engine)
            existing_tables = inspector.get_table_names()
            
            if 'job_file_statuses' not in existing_tables:
                # Tabulka neexistuje, vytvořit ji
                with self.engine.begin() as conn:
                    conn.execute(text("""
                        CREATE TABLE job_file_statuses (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            job_id INTEGER NOT NULL,
                            file_path TEXT NOT NULL,
                            file_size INTEGER NOT NULL,
                            status TEXT NOT NULL,
                            error_message TEXT,
                            copied_at DATETIME,
                            FOREIGN KEY (job_id) REFERENCES job_runs(id)
                        )
                    """))
                    conn.execute(text("CREATE INDEX idx_job_file_statuses_job_id ON job_file_statuses(job_id)"))
                    print("Migration: Created job_file_statuses table")
            else:
                print("Migration: job_file_statuses table already exists")
        except Exception as e:
            print(f"Migration error: {e}")
            import traceback
            traceback.print_exc()
    
    async def _migrate_batches_include_extra(self):
        """Migrace: přidá include_extra sloupec do batches tabulky pokud neexistuje"""
        try:
            from sqlalchemy import text
            with self.engine.begin() as conn:
                result = conn.execute(text("""
                    SELECT COUNT(*) FROM pragma_table_info('batches') WHERE name='include_extra'
                """))
                count = result.scalar()
                if count == 0:
                    conn.execute(text("ALTER TABLE batches ADD COLUMN include_extra BOOLEAN DEFAULT 0"))
                    print("Migration: Added include_extra column to batches table")
                else:
                    print("Migration: include_extra column already exists")
        except Exception as e:
            print(f"Migration error: {e}")
            import traceback
            traceback.print_exc()
    
    async def _migrate_diffs_error_message(self):
        """Migrace: přidá error_message sloupec do diffs tabulky pokud neexistuje"""
        try:
            from sqlalchemy import text
            with self.engine.begin() as conn:
                # Zkontrolovat, zda sloupec existuje
                result = conn.execute(text("""
                    SELECT COUNT(*) FROM pragma_table_info('diffs') WHERE name='error_message'
                """))
                count = result.scalar()
                
                if count == 0:
                    # Sloupec neexistuje, přidat ho
                    conn.execute(text("ALTER TABLE diffs ADD COLUMN error_message TEXT"))
                    print("Migration: Added error_message column to diffs table")
                else:
                    print("Migration: error_message column already exists in diffs table")
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

