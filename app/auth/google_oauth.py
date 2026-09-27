import os
import requests
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

router = APIRouter()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

SCOPE = "https://www.googleapis.com/auth/gmail.readonly email profile"


@router.get("/login")
def google_login():
    url = (
        f"{AUTH_URL}"
        f"?client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={GOOGLE_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={SCOPE}"
        f"&access_type=offline"
        f"&prompt=consent"
    )
    return RedirectResponse(url)


@router.get("/callback")
def google_callback(request: Request, code: str):
    # Exchange code for tokens
    data = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code",
    }

    token_response = requests.post(TOKEN_URL, data=data)
    tokens = token_response.json()

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")

    # Fetch user info
    user_info = requests.get(
        USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"}
    ).json()

    # TODO: Save tokens + user info to your database

    return {
        "message": "Google OAuth successful",
        "user": user_info,
        "access_token": access_token,
        "refresh_token": refresh_token,
    }
