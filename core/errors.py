"""
Esquema de errores unificado para la API.
"""
from pydantic import BaseModel
from typing import Optional, Any


class ErrorResponse(BaseModel):
    """Respuesta de error consistente para todos los endpoints."""
    success: bool = False
    error: str
    detail: Optional[Any] = None
    status_code: int


class SuccessResponse(BaseModel):
    """Respuesta exitosa consistente."""
    success: bool = True
    message: Optional[str] = None
    data: Optional[Any] = None
