from fastapi import Request

from app.db.supabase_client import Repository


def get_repository(request: Request) -> Repository:
    return request.app.state.repository
