"""
Pydantic Response Models
"""
from pydantic import BaseModel
from typing import Optional, Any, Dict

class JobResponse(BaseModel):
    job_id: str
    status: str
    message: str

class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    progress: int
    created_at: str
    completed_at: Optional[str] = None

class JobResultResponse(BaseModel):
    job_id: str
    status: str
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None

class HealthResponse(BaseModel):
    status: str
    timestamp: str
    database: Dict[str, Any]
    system: Dict[str, Any]
