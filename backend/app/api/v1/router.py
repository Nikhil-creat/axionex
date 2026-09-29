from fastapi import APIRouter, Depends

from app.core.ratelimit import rate_limit

from app.api.v1.endpoints import agents, billing, compliance, insights, rag_query, vision, webhooks

api_router = APIRouter()
for module in (agents, insights, vision, rag_query, billing, compliance):
    api_router.include_router(module.router, dependencies=[Depends(rate_limit)])
api_router.include_router(webhooks.router)  # webhooks authenticate with HMAC signatures instead
