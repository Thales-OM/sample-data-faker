from fastapi import APIRouter
from .table import router as table_router
from .openmetadata import router as openmetadata_router
from .dto import router as dto_router

router = APIRouter(prefix="/v1")
router.include_router(router=table_router)
router.include_router(router=openmetadata_router)
router.include_router(router=dto_router)
