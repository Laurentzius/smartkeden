from typing import Optional
from fastapi import Header, HTTPException, status
from app.core.config import settings


async def verify_admin_key(
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key"),
):
    """FastAPI dependency: validates the X-Admin-Key header against ADMIN_API_KEY."""
    if not x_admin_key or x_admin_key != settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing admin API key",
        )
    return x_admin_key
