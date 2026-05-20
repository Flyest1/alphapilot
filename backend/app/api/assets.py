from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_repository
from app.db.supabase_client import Repository
from app.models.asset import AssetCreate, AssetRead, AssetUpdate

router = APIRouter(prefix="/api/assets", tags=["assets"])


@router.get("", response_model=list[AssetRead])
def list_assets(repository: Repository = Depends(get_repository)) -> list[dict]:
    return repository.list_assets()


@router.post("", response_model=AssetRead, status_code=status.HTTP_201_CREATED)
def create_asset(
    payload: AssetCreate,
    repository: Repository = Depends(get_repository),
) -> dict:
    return repository.create_asset(payload.model_dump())


@router.put("/{asset_id}", response_model=AssetRead)
def update_asset(
    asset_id: str,
    payload: AssetUpdate,
    repository: Repository = Depends(get_repository),
) -> dict:
    updated = repository.update_asset(asset_id, payload.model_dump(exclude_unset=True))
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="asset not found")
    return updated


@router.delete("/{asset_id}")
def delete_asset(
    asset_id: str, repository: Repository = Depends(get_repository)
) -> dict[str, bool]:
    deleted = repository.delete_asset(asset_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="asset not found")
    return {"deleted": True}
