"""
Adapter factory - vytváří adaptéry podle konfigurace
"""
from backend.adapters.local_scan import LocalScanAdapter
from backend.adapters.ssh_scan import SshScanAdapter
from backend.adapters.local_transfer import LocalRsyncTransferAdapter
from backend.adapters.ssh_transfer import SshRsyncTransferAdapter
from backend.database import Dataset

class AdapterFactory:
    """Factory pro vytváření adapterů"""
    
    @staticmethod
    def create_scan_adapter(dataset: Dataset, location: str) -> "ScanAdapter":
        """Vytvoří scan adapter podle konfigurace datasetu"""
        config = dataset.scan_adapter_config or {}
        
        if dataset.scan_adapter_type == "local":
            if location == "NAS1":
                return LocalScanAdapter(base_path="/mnt/nas1")
            elif location == "USB":
                return LocalScanAdapter(base_path="/mnt/usb")
            elif location == "NAS2":
                return LocalScanAdapter(base_path="/mnt/nas2")
            else:
                raise ValueError(f"Unknown location for local adapter: {location}")
        
        elif dataset.scan_adapter_type == "ssh":
            return SshScanAdapter(
                host=config.get("host", ""),
                port=config.get("port", 22),
                username=config.get("username", ""),
                password=config.get("password", ""),
                key_file=config.get("key_file"),
                base_path=config.get("base_path", "/")
            )
        
        else:
            raise ValueError(f"Unknown scan adapter type: {dataset.scan_adapter_type}")
    
    @staticmethod
    def create_transfer_adapter(dataset: Dataset) -> "TransferAdapter":
        """Vytvoří transfer adapter podle konfigurace datasetu"""
        config = dataset.transfer_adapter_config or {}
        
        if dataset.transfer_adapter_type == "local":
            return LocalRsyncTransferAdapter()
        
        elif dataset.transfer_adapter_type == "ssh":
            return SshRsyncTransferAdapter(
                host=config.get("host", ""),
                port=config.get("port", 22),
                username=config.get("username", ""),
                password=config.get("password", ""),
                key_file=config.get("key_file")
            )
        
        else:
            raise ValueError(f"Unknown transfer adapter type: {dataset.transfer_adapter_type}")

