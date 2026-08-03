from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .seed import seed
from .storage import UPLOAD_DIR
from .routers import (
    auth, users, roles, projects, campaigns, tracking, email, sms, channels, dashboard, suppressions, admin_smtp,
    templates,
)

app = FastAPI(title="Reach API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


@app.on_event("startup")
def on_startup():
    seed()


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "reach-api"}


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(roles.router)
app.include_router(projects.router)
app.include_router(campaigns.router)
app.include_router(tracking.router)
app.include_router(email.router)
app.include_router(sms.router)
app.include_router(channels.router)
app.include_router(dashboard.router)
app.include_router(suppressions.router)
app.include_router(admin_smtp.router)
app.include_router(templates.router)
