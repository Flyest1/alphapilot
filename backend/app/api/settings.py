from fastapi import APIRouter, Depends

from app.api.dependencies import get_repository
from app.config import get_env_application_defaults, resolve_application_settings
from app.db.supabase_client import Repository
from app.models.settings import Settings, SettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=Settings)
def get_settings(repository: Repository = Depends(get_repository)) -> Settings:
    return resolve_application_settings(repository.get_settings(), get_env_application_defaults())


@router.post("", response_model=Settings)
def save_settings(
    payload: SettingsUpdate,
    repository: Repository = Depends(get_repository),
) -> Settings:
    current = resolve_application_settings(
        repository.get_settings(), get_env_application_defaults()
    )
    update_values = payload.model_dump(exclude_unset=True)
    merged = current.model_dump()
    merged.update(update_values)
    saved = repository.upsert_settings(merged)
    return resolve_application_settings(saved, get_env_application_defaults())
