"""
Base interfaces pro adaptéry
"""
from abc import ABC, abstractmethod
from typing import Iterator, Callable, Optional, List
from dataclasses import dataclass

@dataclass
class FileEntry:
    """Reprezentace souboru"""
    full_rel_path: str
    size: int
    mtime_epoch: float
    root_rel_path: str

class ScanAdapter(ABC):
    """Rozhraní pro scan adaptéry - pouze listování souborů"""
    
    @abstractmethod
    def list_files(
        self,
        roots: List[str],
        progress_cb: Optional[Callable[[int, str], None]] = None,
        log_cb: Optional[Callable[[str], None]] = None
    ) -> Iterator[FileEntry]:
        """
        Vrátí iterator FileEntry pro všechny soubory v roots.
        Nesmí kopírovat data, pouze listovat.
        """
        pass

class TransferAdapter(ABC):
    """Rozhraní pro transfer adaptéry - kopírování souborů"""
    
    @abstractmethod
    def send_batch(
        self,
        files: List[FileEntry],
        source_base: str,
        target_base: str,
        dry_run: bool = False,
        progress_cb: Optional[Callable[[int, str], None]] = None,
        log_cb: Optional[Callable[[str], None]] = None
    ) -> dict:
        """
        Zkopíruje soubory z source_base do target_base.
        Pracuje pouze s batch items - nerozhoduje co kopírovat.
        """
        pass

