"""
Database models a konfigurace
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, JSON, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import os

Base = declarative_base()

def get_db_path() -> str:
    """Vrátí cestu k databázi (na USB)"""
    db_path = os.getenv("DATABASE_PATH", "/mnt/usb/sync_orchestrator.db")
    return db_path

# Dataset - logická migrační jednotka
class Dataset(Base):
    __tablename__ = "datasets"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    location = Column(String, nullable=False)  # NAS1/USB/NAS2
    roots = Column(JSON, nullable=False)  # List root složek
    scan_adapter_type = Column(String, nullable=False)  # local/ssh
    scan_adapter_config = Column(JSON)  # SSH parametry atd.
    transfer_adapter_type = Column(String, nullable=False)  # local/ssh
    transfer_adapter_config = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)

# Scan - snapshot souborových metadat
class Scan(Base):
    __tablename__ = "scans"
    
    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="pending")  # pending/running/completed/failed
    total_files = Column(Integer, default=0)
    total_size = Column(Float, default=0.0)
    error_message = Column(Text)  # Chybová zpráva při selhání
    
    dataset = relationship("Dataset", backref="scans")

# FileEntry - záznam o souboru ve scanu
class FileEntry(Base):
    __tablename__ = "file_entries"
    
    id = Column(Integer, primary_key=True, index=True)
    scan_id = Column(Integer, ForeignKey("scans.id"), nullable=False)
    full_rel_path = Column(String, nullable=False, index=True)
    size = Column(Integer, nullable=False)
    mtime_epoch = Column(Float, nullable=False)
    root_rel_path = Column(String, nullable=False)
    
    scan = relationship("Scan", backref="file_entries")
    
    __table_args__ = (
        {"sqlite_autoincrement": True},
    )

# Diff - porovnání dvou scanů
class Diff(Base):
    __tablename__ = "diffs"
    
    id = Column(Integer, primary_key=True, index=True)
    source_scan_id = Column(Integer, ForeignKey("scans.id"), nullable=False)
    target_scan_id = Column(Integer, ForeignKey("scans.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="pending")  # pending/running/completed/failed
    error_message = Column(Text)  # Chybová zpráva při selhání
    
    source_scan = relationship("Scan", foreign_keys=[source_scan_id], backref="source_diffs")
    target_scan = relationship("Scan", foreign_keys=[target_scan_id], backref="target_diffs")

# DiffItem - výsledek diffu pro soubor
class DiffItem(Base):
    __tablename__ = "diff_items"
    
    id = Column(Integer, primary_key=True, index=True)
    diff_id = Column(Integer, ForeignKey("diffs.id"), nullable=False)
    full_rel_path = Column(String, nullable=False, index=True)
    source_size = Column(Integer)
    target_size = Column(Integer)
    source_mtime = Column(Float)
    target_mtime = Column(Float)
    category = Column(String, nullable=False)  # missing/same/conflict
    
    diff = relationship("Diff", backref="items")

# Batch - plán přenosu
class Batch(Base):
    __tablename__ = "batches"
    
    id = Column(Integer, primary_key=True, index=True)
    diff_id = Column(Integer, ForeignKey("diffs.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    usb_limit_pct = Column(Float, default=80.0)
    include_conflicts = Column(Boolean, default=False)
    include_extra = Column(Boolean, default=False)
    exclude_patterns = Column(JSON, default=list)
    status = Column(String, default="pending")  # pending/running/ready/failed/completed
    error_message = Column(Text)  # Chybová zpráva při selhání
    
    diff = relationship("Diff", backref="batches")

# BatchItem
class BatchItem(Base):
    __tablename__ = "batch_items"
    
    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("batches.id"), nullable=False)
    full_rel_path = Column(String, nullable=False)
    size = Column(Integer, nullable=False)
    category = Column(String, nullable=False)  # missing/conflict
    enabled = Column(Boolean, default=True)  # Zda je soubor povolen ke kopírování
    
    batch = relationship("Batch", backref="items")

# JobRun - audit operací
class JobRun(Base):
    __tablename__ = "job_runs"
    
    id = Column(Integer, primary_key=True, index=True)
    type = Column(String, nullable=False)  # scan/diff/batch/copy
    status = Column(String, default="running")  # running/completed/failed
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime)
    error_message = Column(Text)
    job_log = Column(Text)  # Log zprávy z jobu
    job_metadata = Column("job_metadata", JSON)  # Dodatečné informace o jobu (metadata je rezervované slovo v SQLAlchemy)
    
    file_statuses = relationship("JobFileStatus", backref="job_run", cascade="all, delete-orphan")

# JobFileStatus - stav každého souboru v copy jobu
class JobFileStatus(Base):
    __tablename__ = "job_file_statuses"
    
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("job_runs.id"), nullable=False)
    file_path = Column(String, nullable=False)
    file_size = Column(Integer, nullable=False)
    status = Column(String, nullable=False)  # copied/failed/skipped
    error_message = Column(Text)  # Chybová zpráva pokud selhalo
    copied_at = Column(DateTime)

