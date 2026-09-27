from fastapi import FastAPI

from app.gmail_routes import router as gmail_router
from app.auth.google_oauth import router as google_router

from app.debug_routes import router as debug_router
app.include_router(debug_router)

app = FastAPI()

@app.get("/")
def root():
    return {"status": "ok"}

# Include Google OAuth routes
app.include_router(google_router, prefix="/auth/google")

# Include Gmail routes
app.include_router(gmail_router, prefix="/gmail", tags=["gmail"])