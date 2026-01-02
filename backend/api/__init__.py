from fastapi import APIRouter
from backend.api import health, mounts, datasets, scans, diffs, batches, copy

router = APIRouter()

router.include_router(health.router, tags=["health"])
router.include_router(mounts.router, prefix="/mounts", tags=["mounts"])
router.include_router(datasets.router, prefix="/datasets", tags=["datasets"])
router.include_router(scans.router, prefix="/scans", tags=["scans"])
router.include_router(diffs.router, prefix="/diffs", tags=["diffs"])
router.include_router(batches.router, prefix="/batches", tags=["batches"])
router.include_router(copy.router, prefix="/copy", tags=["copy"])

