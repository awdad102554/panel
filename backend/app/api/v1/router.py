from fastapi import APIRouter

from app.api.v1 import (
    ai,
    ai_models,
    auth,
    case_portrait,
    cases,
    dashboard,
    documents,
    internal_cases,
    service_delivery,
    settings,
    stats,
    timeline,
    virtual_cases,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(dashboard.router)
api_router.include_router(cases.router)
api_router.include_router(case_portrait.router)
api_router.include_router(timeline.router)
api_router.include_router(ai.router)
api_router.include_router(ai_models.router)
api_router.include_router(internal_cases.router)
api_router.include_router(documents.router)
api_router.include_router(service_delivery.router)
api_router.include_router(stats.router)
api_router.include_router(settings.router)
api_router.include_router(virtual_cases.router)
