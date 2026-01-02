"""
Mount status service - monitoruje dostupnost NAS1/USB/NAS2
"""
import os
import asyncio
import shutil
from typing import Dict, Optional
from backend.websocket_manager import websocket_manager
from backend.storage_service import storage_service

class MountService:
    def __init__(self):
        self.mounts = {
            "nas1": "/mnt/nas1",  # Může být prázdný, pokud se používá SSH adapter
            "usb": "/mnt/usb",
            "nas2": "/mnt/nas2"  # Může být prázdný, pokud se používá SSH adapter
        }
        self.status = {
            "nas1": {"available": False, "path": "/mnt/nas1", "writable": False},
            "usb": {"available": False, "path": "/mnt/usb", "writable": False},
            "nas2": {"available": False, "path": "/mnt/nas2", "writable": False},
            "safe_mode": True
        }
        self.monitoring = False
        self.monitor_task: Optional[asyncio.Task] = None

    async def check_mount(self, name: str, path: str, writable: bool = False) -> Dict:
        """Ověří dostupnost mount pointu"""
        result = {
            "available": False,
            "path": path,
            "writable": False,
            "error": None,
            "total_size": 0,
            "used_size": 0,
            "free_size": 0
        }
        
        try:
            # Kontrola existence
            if not os.path.exists(path):
                result["error"] = "Path does not exist"
                return result
            
            # Kontrola, zda je to mount point (nebo alespoň adresář)
            if not os.path.isdir(path):
                result["error"] = "Path is not a directory"
                return result
            
            # Kontrola, zda je to skutečný mount (pokud je to mount point, měl by být v /proc/mounts)
            # Pro jednoduchost kontrolujeme jen existenci a přístupnost
            result["available"] = True
            
            # Získání velikosti disku
            try:
                stat = shutil.disk_usage(path)
                result["total_size"] = stat.total
                result["used_size"] = stat.used
                result["free_size"] = stat.free
            except Exception as e:
                # Pokud se nepodaří získat velikost, není to kritické
                pass
            
            # Test zápisu (pokud je požadován)
            if writable:
                test_file = os.path.join(path, ".sync_test_write")
                try:
                    with open(test_file, "w") as f:
                        f.write("test")
                    os.remove(test_file)
                    result["writable"] = True
                except (OSError, PermissionError) as e:
                    result["error"] = f"Write test failed: {str(e)}"
                    result["writable"] = False
            else:
                # Pro read-only stačí kontrola existence
                result["writable"] = False
                
        except Exception as e:
            result["error"] = str(e)
        
        return result

    async def check_mounts(self):
        """Zkontroluje všechny mounty"""
        nas1_status = await self.check_mount("nas1", self.mounts["nas1"], writable=False)
        usb_status = await self.check_mount("usb", self.mounts["usb"], writable=True)
        nas2_status = await self.check_mount("nas2", self.mounts["nas2"], writable=True)
        
        old_safe_mode = self.status["safe_mode"]
        
        self.status["nas1"] = nas1_status
        self.status["usb"] = usb_status
        self.status["nas2"] = nas2_status
        self.status["safe_mode"] = not usb_status["available"] or not usb_status["writable"]
        
        # Broadcast změny stavu
        await websocket_manager.broadcast({
            "type": "mounts.status",
            "data": self.status
        })
        
        # Pokud se změnil SAFE MODE, broadcast specifický event
        if old_safe_mode != self.status["safe_mode"]:
            if self.status["safe_mode"]:
                await storage_service.handle_unavailable("USB mount unavailable")
                await websocket_manager.broadcast({
                    "type": "storage.db.unavailable",
                    "data": {"reason": "USB mount unavailable"}
                })
            else:
                await storage_service.handle_available()
                await websocket_manager.broadcast({
                    "type": "storage.db.available",
                    "data": {}
                })
        
        return self.status

    async def get_status(self) -> Dict:
        """Vrátí aktuální stav"""
        return self.status.copy()

    async def start_monitoring(self, interval: int = 10):
        """Spustí periodické monitorování mountů"""
        if self.monitoring:
            return
        
        self.monitoring = True
        
        async def monitor_loop():
            while self.monitoring:
                await self.check_mounts()
                await asyncio.sleep(interval)
        
        self.monitor_task = asyncio.create_task(monitor_loop())
        # První kontrola okamžitě
        await self.check_mounts()

    async def stop_monitoring(self):
        """Zastaví monitorování"""
        self.monitoring = False
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass

mount_service = MountService()

