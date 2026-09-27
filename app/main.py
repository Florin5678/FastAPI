from fastapi import FastAPI, Depends

from app.gmail_routes import router as gmail_router
from app.summary_routes import router as summary_router
from app.auth.google_oauth import router as google_router
from app.security import require_api_key

app = FastAPI()

@app.get("/")
def root():
    return {"status": "ok"}

# Include Google OAuth routes (public - Google redirects the browser here)
app.include_router(google_router, prefix="/auth/google")

# Everything that exposes mail data requires the X-API-Key header
protected = [Depends(require_api_key)]

# Include Gmail routes
app.include_router(gmail_router, prefix="/gmail", tags=["gmail"], dependencies=protected)

# Include summary + digest routes
app.include_router(summary_router, tags=["summaries"], dependencies=protected)
