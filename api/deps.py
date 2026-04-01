from fastapi import HTTPException, Depends
from fastapi.security import APIKeyHeader
from db.database import get_tenant_by_api_key

api_key_header = APIKeyHeader(name="X-API-Key")


async def get_tenant(api_key: str = Depends(api_key_header)):
    tenant = await get_tenant_by_api_key(api_key)
    if not tenant:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return tenant
