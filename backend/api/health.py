"""
Health check endpoint - vždy dostupný, i v SAFE MODE
"""
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

class HealthResponse(BaseModel):
    status: str
    version: str

@router.get("/health")
async def health_check():
    """Health check endpoint - whitelisted v SAFE MODE"""
    return HealthResponse(status="ok", version="1.0.0")

