from fastapi import APIRouter

from app.api.v1 import (
    ai,
    ai_models,
    auth,
    case_portrait,
    case_tags,
    cases,
    dashboard,
    documents,
    internal_cases,
    reserve_review,
    service_delivery,
    settings,
    stats,
    tianyancha,
    timeline,
    user_bindings,
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
api_router.include_router(case_tags.router)
api_router.include_router(user_bindings.router)
api_router.include_router(reserve_review.router)
api_router.include_router(documents.router)
api_router.include_router(service_delivery.router)
api_router.include_router(stats.router)
api_router.include_router(settings.router)
api_router.include_router(virtual_cases.router)
api_router.include_router(tianyancha.router)
