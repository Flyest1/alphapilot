from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_repository
from app.db.supabase_client import Repository
from app.models.candidate_asset import (
    CandidateAssetCreate,
    CandidateAssetRead,
    CandidateAssetUpdate,
)

router = APIRouter(prefix="/api/candidates", tags=["candidates"])


@router.get("", response_model=list[CandidateAssetRead])
def list_candidate_assets(repository: Repository = Depends(get_repository)) -> list[dict]:
    return repository.list_candidate_assets()


@router.post("", response_model=CandidateAssetRead, status_code=status.HTTP_201_CREATED)
def create_candidate_asset(
    payload: CandidateAssetCreate,
    repository: Repository = Depends(get_repository),
) -> dict:
    return repository.create_candidate_asset(payload.model_dump())


@router.put("/{candidate_id}", response_model=CandidateAssetRead)
def update_candidate_asset(
    candidate_id: str,
    payload: CandidateAssetUpdate,
    repository: Repository = Depends(get_repository),
) -> dict:
    updated = repository.update_candidate_asset(
        candidate_id, payload.model_dump(exclude_unset=True)
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="candidate asset not found"
        )
    return updated


@router.delete("/{candidate_id}")
def delete_candidate_asset(
    candidate_id: str,
    repository: Repository = Depends(get_repository),
) -> dict[str, bool]:
    deleted = repository.delete_candidate_asset(candidate_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="candidate asset not found"
        )
    return {"deleted": True}
