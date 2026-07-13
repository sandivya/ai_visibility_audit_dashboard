from fastapi import APIRouter

from app.routers import audits, auth_health, outputs, projects

router = APIRouter()
router.include_router(auth_health.router)
router.include_router(projects.router)
router.include_router(audits.router)
router.include_router(outputs.router)
