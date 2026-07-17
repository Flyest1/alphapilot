"""Read-only source providers for manual advisory analyses."""

from app.services.advisory.providers.sec_edgar import SecEdgarProvider

__all__ = ["SecEdgarProvider"]
