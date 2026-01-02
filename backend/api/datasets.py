"""
Dataset API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime

from backend.storage_service import storage_service
from backend.database import Dataset
from backend.mount_service import mount_service

router = APIRouter()

class DatasetCreate(BaseModel):
    name: str
    location: str  # NAS1/USB/NAS2
    roots: List[str]
    scan_adapter_type: str = "local"  # local/ssh
    scan_adapter_config: Optional[Dict[str, Any]] = None
    transfer_adapter_type: str = "local"  # local/ssh
    transfer_adapter_config: Optional[Dict[str, Any]] = None

class DatasetUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    roots: Optional[List[str]] = None
    scan_adapter_type: Optional[str] = None
    scan_adapter_config: Optional[Dict[str, Any]] = None
    transfer_adapter_type: Optional[str] = None
    transfer_adapter_config: Optional[Dict[str, Any]] = None

class DatasetResponse(BaseModel):
    id: int
    name: str
    location: str
    roots: List[str]
    scan_adapter_type: str
    scan_adapter_config: Optional[Dict[str, Any]]
    transfer_adapter_type: str
    transfer_adapter_config: Optional[Dict[str, Any]]
    created_at: datetime
    
    model_config = {"from_attributes": True}

async def check_safe_mode():
    """Dependency - kontroluje SAFE MODE"""
    mount_status = await mount_service.get_status()
    if mount_status.get("safe_mode", True):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SAFE MODE: USB/DB unavailable"
        )

@router.post("/", response_model=DatasetResponse)
async def create_dataset(dataset_data: DatasetCreate, _: None = Depends(check_safe_mode)):
    """Vytvořit nový dataset"""
    session = storage_service.get_session()
    if not session:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        # Kontrola, zda dataset se stejným názvem už neexistuje
        existing = session.query(Dataset).filter(Dataset.name == dataset_data.name).first()
        if existing:
            raise HTTPException(status_code=400, detail="Dataset with this name already exists")
        
        # Validace - pouze jedna root složka
        if not dataset_data.roots or len(dataset_data.roots) == 0:
            raise HTTPException(status_code=400, detail="At least one root path is required")
        if len(dataset_data.roots) > 1:
            raise HTTPException(status_code=400, detail="Only one root path is allowed per dataset. Create multiple datasets for multiple root paths.")
        
        dataset = Dataset(
            name=dataset_data.name,
            location=dataset_data.location,
            roots=dataset_data.roots[:1],  # Pouze první root složka
            scan_adapter_type=dataset_data.scan_adapter_type,
            scan_adapter_config=dataset_data.scan_adapter_config,
            transfer_adapter_type=dataset_data.transfer_adapter_type,
            transfer_adapter_config=dataset_data.transfer_adapter_config
        )
        session.add(dataset)
        session.commit()
        session.refresh(dataset)
        
        return DatasetResponse.model_validate(dataset)
    finally:
        session.close()

@router.get("/", response_model=List[DatasetResponse])
async def list_datasets():
    """Seznam všech datasetů"""
    session = storage_service.get_session()
    if not session:
        return []
    
    try:
        datasets = session.query(Dataset).order_by(Dataset.created_at.desc()).all()
        return [DatasetResponse.model_validate(d) for d in datasets]
    finally:
        session.close()

@router.get("/{dataset_id}", response_model=DatasetResponse)
async def get_dataset(dataset_id: int):
    """Detail datasetu"""
    session = storage_service.get_session()
    if not session:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        dataset = session.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset:
            raise HTTPException(status_code=404, detail="Dataset not found")
        return DatasetResponse.model_validate(dataset)
    finally:
        session.close()

@router.put("/{dataset_id}", response_model=DatasetResponse)
async def update_dataset(dataset_id: int, dataset_data: DatasetUpdate, _: None = Depends(check_safe_mode)):
    """Aktualizovat dataset"""
    session = storage_service.get_session()
    if not session:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        dataset = session.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset:
            raise HTTPException(status_code=404, detail="Dataset not found")
        
        # Aktualizace pouze poskytnutých polí
        if dataset_data.name is not None:
            # Kontrola unikátnosti názvu
            existing = session.query(Dataset).filter(
                Dataset.name == dataset_data.name,
                Dataset.id != dataset_id
            ).first()
            if existing:
                raise HTTPException(status_code=400, detail="Dataset with this name already exists")
            dataset.name = dataset_data.name
        
        if dataset_data.location is not None:
            dataset.location = dataset_data.location
        if dataset_data.roots is not None:
            # Validace - pouze jedna root složka
            if len(dataset_data.roots) == 0:
                raise HTTPException(status_code=400, detail="At least one root path is required")
            if len(dataset_data.roots) > 1:
                raise HTTPException(status_code=400, detail="Only one root path is allowed per dataset. Create multiple datasets for multiple root paths.")
            dataset.roots = dataset_data.roots[:1]  # Pouze první root složka
        if dataset_data.scan_adapter_type is not None:
            dataset.scan_adapter_type = dataset_data.scan_adapter_type
        if dataset_data.scan_adapter_config is not None:
            dataset.scan_adapter_config = dataset_data.scan_adapter_config
        if dataset_data.transfer_adapter_type is not None:
            dataset.transfer_adapter_type = dataset_data.transfer_adapter_type
        if dataset_data.transfer_adapter_config is not None:
            dataset.transfer_adapter_config = dataset_data.transfer_adapter_config
        
        session.commit()
        session.refresh(dataset)
        
        return DatasetResponse.model_validate(dataset)
    finally:
        session.close()

@router.delete("/{dataset_id}")
async def delete_dataset(dataset_id: int, _: None = Depends(check_safe_mode)):
    """Smazat dataset"""
    session = storage_service.get_session()
    if not session:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        dataset = session.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset:
            raise HTTPException(status_code=404, detail="Dataset not found")
        
        session.delete(dataset)
        session.commit()
        
        return {"message": "Dataset deleted"}
    finally:
        session.close()

@router.get("/{dataset_id}/test-connection")
async def test_dataset_connection(dataset_id: int):
    """Otestovat připojení k datasetu"""
    session = storage_service.get_session()
    if not session:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        dataset = session.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset:
            raise HTTPException(status_code=404, detail="Dataset not found")
        
        # Test připojení podle typu adapteru
        if dataset.scan_adapter_type == "local":
            # Pro local adapter zkontrolujeme mount point
            import os
            mount_paths = {
                "NAS1": "/mnt/nas1",
                "USB": "/mnt/usb",
                "NAS2": "/mnt/nas2"
            }
            mount_path = mount_paths.get(dataset.location)
            
            if not mount_path:
                return {
                    "connected": False,
                    "error": f"Unknown location: {dataset.location}"
                }
            
            # Kontrola existence a přístupnosti
            if not os.path.exists(mount_path):
                return {
                    "connected": False,
                    "error": f"Mount point does not exist: {mount_path}"
                }
            
            if not os.path.isdir(mount_path):
                return {
                    "connected": False,
                    "error": f"Mount point is not a directory: {mount_path}"
                }
            
            # Test přístupnosti - zkusíme listovat adresář
            try:
                os.listdir(mount_path)
                return {
                    "connected": True,
                    "message": f"Mount point accessible: {mount_path}"
                }
            except (OSError, PermissionError) as e:
                return {
                    "connected": False,
                    "error": f"Cannot access mount point: {str(e)}"
                }
        
        elif dataset.scan_adapter_type == "ssh":
            # Pro SSH adapter zkusíme připojení
            config = dataset.scan_adapter_config or {}
            host = config.get("host", "")
            port = config.get("port", 22)
            username = config.get("username", "")
            password = config.get("password", "")
            key_file = config.get("key_file")
            base_path = config.get("base_path", "/")
            
            if not host or not username:
                return {
                    "connected": False,
                    "error": "SSH host or username not configured"
                }
            
            try:
                import paramiko
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                if key_file:
                    client.connect(
                        hostname=host,
                        port=port,
                        username=username,
                        key_filename=key_file,
                        timeout=5
                    )
                else:
                    if not password:
                        return {
                            "connected": False,
                            "error": "SSH password not configured"
                        }
                    client.connect(
                        hostname=host,
                        port=port,
                        username=username,
                        password=password,
                        timeout=5
                    )
                
                # Test SFTP připojení a přístupnosti base_path
                sftp = client.open_sftp()
                try:
                    sftp.listdir(base_path)
                    sftp.close()
                    client.close()
                    return {
                        "connected": True,
                        "message": f"SSH connection successful to {username}@{host}:{port}, base path: {base_path}"
                    }
                except Exception as e:
                    sftp.close()
                    client.close()
                    return {
                        "connected": False,
                        "error": f"Cannot access base path {base_path}: {str(e)}"
                    }
            except paramiko.AuthenticationException:
                return {
                    "connected": False,
                    "error": "SSH authentication failed"
                }
            except paramiko.SSHException as e:
                return {
                    "connected": False,
                    "error": f"SSH connection error: {str(e)}"
                }
            except Exception as e:
                return {
                    "connected": False,
                    "error": f"Connection test failed: {str(e)}"
                }
        
        else:
            return {
                "connected": False,
                "error": f"Unknown adapter type: {dataset.scan_adapter_type}"
            }
    
    finally:
        session.close()

@router.get("/browse-local")
async def browse_local_path(location: str, path: str = "/"):
    """Procházet lokální filesystém podle location (bez datasetu - pro nové datasety)"""
    import os
    mount_paths = {
        "NAS1": "/mnt/nas1",
        "USB": "/mnt/usb",
        "NAS2": "/mnt/nas2"
    }
    mount_path = mount_paths.get(location)
    
    if not mount_path:
        raise HTTPException(status_code=400, detail=f"Unknown location: {location}")
    
    # Normalizace cesty - pokud path začíná /, použijeme ho přímo, jinak relativně k mount_path
    if path.startswith("/"):
        # Absolutní cesta - použijeme ji přímo
        full_path = path
    else:
        # Relativní cesta - přidáme k mount_path
        full_path = os.path.join(mount_path, path.lstrip("/"))
    
    # Normalizace cesty (odstranění dvojitých lomítek, atd.)
    full_path = os.path.normpath(full_path)
    
    # Bezpečnostní kontrola - musí být pod mount_path
    if not full_path.startswith(os.path.abspath(mount_path)):
        raise HTTPException(status_code=403, detail="Path outside mount point")
    
    # Kontrola existence
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail=f"Path does not exist: {full_path}")
    
    if not os.path.isdir(full_path):
        raise HTTPException(status_code=400, detail=f"Path is not a directory: {full_path}")
    
    # Listovat obsah adresáře
    items = []
    try:
        for item_name in os.listdir(full_path):
            item_path = os.path.join(full_path, item_name)
            try:
                is_item_dir = os.path.isdir(item_path)
                stat_info = os.stat(item_path)
                items.append({
                    "name": item_name,
                    "path": item_path,  # Vracíme absolutní cestu
                    "is_directory": is_item_dir,
                    "size": stat_info.st_size if not is_item_dir else None,
                    "modified": stat_info.st_mtime
                })
            except (OSError, PermissionError) as e:
                # Pokud nelze získat stat, přidat alespoň název
                items.append({
                    "name": item_name,
                    "path": item_path,
                    "is_directory": None,
                    "size": None,
                    "modified": None,
                    "error": str(e)
                })
    except (OSError, PermissionError) as e:
        raise HTTPException(status_code=500, detail=f"Cannot list directory: {str(e)}")
    
    # Seřadit - adresáře první, pak soubory
    items.sort(key=lambda x: (x["is_directory"] is False, x["name"].lower()))
    
    # Relativní cesta pro zobrazení (relativně k mount_path)
    relative_path = os.path.relpath(full_path, mount_path)
    if relative_path == ".":
        relative_path = "/"
    else:
        relative_path = "/" + relative_path.replace("\\", "/")
    
    return {
        "path": full_path,  # Absolutní cesta
        "relative_path": relative_path,  # Relativní cesta pro zobrazení
        "items": items,
        "mount_path": mount_path
    }

@router.get("/{dataset_id}/browse")
async def browse_dataset_path(dataset_id: int, path: str = "/"):
    """Procházet adresáře na SSH hostovi (pouze pro SSH adaptéry) nebo lokální filesystém (pouze pro local adaptéry)"""
    session = storage_service.get_session()
    if not session:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        dataset = session.query(Dataset).filter(Dataset.id == dataset_id).first()
        if not dataset:
            raise HTTPException(status_code=404, detail="Dataset not found")
        
        # Lokální browse
        if dataset.scan_adapter_type == "local":
            import os
            mount_paths = {
                "NAS1": "/mnt/nas1",
                "USB": "/mnt/usb",
                "NAS2": "/mnt/nas2"
            }
            mount_path = mount_paths.get(dataset.location)
            
            if not mount_path:
                raise HTTPException(status_code=400, detail=f"Unknown location: {dataset.location}")
            
            # Normalizace cesty - pokud path začíná /, použijeme ho přímo, jinak relativně k mount_path
            if path.startswith("/"):
                # Absolutní cesta - použijeme ji přímo
                full_path = path
            else:
                # Relativní cesta - přidáme k mount_path
                full_path = os.path.join(mount_path, path.lstrip("/"))
            
            # Normalizace cesty (odstranění dvojitých lomítek, atd.)
            full_path = os.path.normpath(full_path)
            
            # Bezpečnostní kontrola - musí být pod mount_path
            if not full_path.startswith(os.path.abspath(mount_path)):
                raise HTTPException(status_code=403, detail="Path outside mount point")
            
            # Kontrola existence
            if not os.path.exists(full_path):
                raise HTTPException(status_code=404, detail=f"Path does not exist: {full_path}")
            
            if not os.path.isdir(full_path):
                raise HTTPException(status_code=400, detail=f"Path is not a directory: {full_path}")
            
            # Listovat obsah adresáře
            items = []
            try:
                for item_name in os.listdir(full_path):
                    item_path = os.path.join(full_path, item_name)
                    try:
                        is_item_dir = os.path.isdir(item_path)
                        stat_info = os.stat(item_path)
                        items.append({
                            "name": item_name,
                            "path": item_path,  # Vracíme absolutní cestu
                            "is_directory": is_item_dir,
                            "size": stat_info.st_size if not is_item_dir else None,
                            "modified": stat_info.st_mtime
                        })
                    except (OSError, PermissionError) as e:
                        # Pokud nelze získat stat, přidat alespoň název
                        items.append({
                            "name": item_name,
                            "path": item_path,
                            "is_directory": None,
                            "size": None,
                            "modified": None,
                            "error": str(e)
                        })
            except (OSError, PermissionError) as e:
                raise HTTPException(status_code=500, detail=f"Cannot list directory: {str(e)}")
            
            # Seřadit - adresáře první, pak soubory
            items.sort(key=lambda x: (x["is_directory"] is False, x["name"].lower()))
            
            # Relativní cesta pro zobrazení (relativně k mount_path)
            relative_path = os.path.relpath(full_path, mount_path)
            if relative_path == ".":
                relative_path = "/"
            else:
                relative_path = "/" + relative_path.replace("\\", "/")
            
            return {
                "path": full_path,  # Absolutní cesta
                "relative_path": relative_path,  # Relativní cesta pro zobrazení
                "items": items,
                "mount_path": mount_path
            }
        
        # SSH browse
        elif dataset.scan_adapter_type != "ssh":
            raise HTTPException(status_code=400, detail="Browse is only available for SSH or local adapters")
        
        config = dataset.scan_adapter_config or {}
        host = config.get("host", "")
        port = config.get("port", 22)
        username = config.get("username", "")
        password = config.get("password", "")
        key_file = config.get("key_file")
        base_path = config.get("base_path", "/")
        
        if not host or not username:
            raise HTTPException(status_code=400, detail="SSH host or username not configured")
        
        try:
            import paramiko
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            if key_file:
                client.connect(
                    hostname=host,
                    port=port,
                    username=username,
                    key_filename=key_file,
                    timeout=5
                )
            else:
                if not password:
                    raise HTTPException(status_code=400, detail="SSH password not configured")
                client.connect(
                    hostname=host,
                    port=port,
                    username=username,
                    password=password,
                    timeout=5
                )
            
            sftp = client.open_sftp()
            try:
                # Normalizace cesty
                if not path.startswith("/"):
                    path = "/" + path
                
                # Zkusit stat - zjistit, zda je to adresář nebo soubor
                try:
                    stat_info = sftp.stat(path)
                    is_dir = (stat_info.st_mode & 0o170000) == 0o040000
                except FileNotFoundError:
                    raise HTTPException(status_code=404, detail=f"Path does not exist: {path}")
                
                if not is_dir:
                    raise HTTPException(status_code=400, detail=f"Path is not a directory: {path}")
                
                # Listovat obsah adresáře
                items = []
                for item_name in sftp.listdir(path):
                    item_path = f"{path.rstrip('/')}/{item_name}" if path != "/" else f"/{item_name}"
                    try:
                        item_stat = sftp.stat(item_path)
                        is_item_dir = (item_stat.st_mode & 0o170000) == 0o040000
                        items.append({
                            "name": item_name,
                            "path": item_path,
                            "is_directory": is_item_dir,
                            "size": item_stat.st_size if not is_item_dir else None,
                            "modified": item_stat.st_mtime
                        })
                    except Exception:
                        # Pokud nelze získat stat, přidat alespoň název
                        items.append({
                            "name": item_name,
                            "path": item_path,
                            "is_directory": None,
                            "size": None,
                            "modified": None
                        })
                
                # Seřadit - adresáře první, pak soubory
                items.sort(key=lambda x: (x["is_directory"] is False, x["name"].lower()))
                
                return {
                    "path": path,
                    "items": items,
                    "base_path": base_path
                }
            finally:
                sftp.close()
                client.close()
                
        except paramiko.AuthenticationException:
            raise HTTPException(status_code=401, detail="SSH authentication failed")
        except paramiko.SSHException as e:
            raise HTTPException(status_code=500, detail=f"SSH connection error: {str(e)}")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Browse failed: {str(e)}")
    
    finally:
        session.close()

