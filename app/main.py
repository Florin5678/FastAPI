from fastapi import FastAPI
from app.auth.google_oauth import router as google_router

app = FastAPI()

@app.get("/")
def root():
    return {"status": "ok"}

# Include Google OAuth routes
app.include_router(google_router, prefix="/auth/google")