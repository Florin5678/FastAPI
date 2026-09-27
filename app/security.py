# Simple shared-secret protection until real session auth exists on the frontend.
import os
import secrets
from typing import Optional
from fastapi import Header, HTTPException

# Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"
# Set it as API_KEY on Render (and as a GitHub Actions secret for the sync workflow).
API_KEY = os.getenv("API_KEY")


def require_api_key(x_api_key: Optional[str] = Header(default=None)):
    """FastAPI dependency - rejects requests without the right X-API-Key header."""
    if not API_KEY:
        # Fail closed: never serve mail data just because the key wasn't configured
        raise HTTPException(status_code=503, detail="API_KEY is not configured on the server")
    if not x_api_key or not secrets.compare_digest(x_api_key, API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header")
