# Shared helper for calling Google APIs (Calendar, Drive, Sheets) with the user's token.
# Missing permissions / a switched-off API become NeedsSetup, which widgets turn into
# a "connect" or "turn it on" message instead of an error.
from typing import Optional

import requests
from fastapi import HTTPException


class NeedsSetup(Exception):
    def __init__(self, reason: str):
        self.reason = reason  # "permission" (sign in again) | "api_disabled" (enable in Cloud Console)


def google_get(url: str, token: str, params: Optional[dict] = None, service: str = "Google",
               raw: bool = False, not_found: Optional[str] = None):
    """GET a Google API URL. Returns parsed JSON, or the response itself with raw=True
    (for file downloads). not_found: message for a 404 (e.g. a wrong file link)."""
    response = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=30)
    if response.status_code == 403:
        body = response.text
        if "accessNotConfigured" in body or "SERVICE_DISABLED" in body:
            raise NeedsSetup("api_disabled")
        if "insufficient" in body.lower() or "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in body:
            raise NeedsSetup("permission")
    if response.status_code == 401:
        raise NeedsSetup("permission")
    if response.status_code == 404 and not_found:
        raise HTTPException(status_code=404, detail=not_found)
    if not response.ok:
        raise HTTPException(status_code=502, detail=f"{service} returned an error ({response.status_code}). Try again later.")
    return response if raw else response.json()
