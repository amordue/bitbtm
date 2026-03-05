from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from auth import NotAuthenticatedException
from config import SECRET_KEY
from database import create_tables
from routes.admin import router as admin_router
from routes.auth import router as auth_router

app = FastAPI(title="BitBT – Robot Combat Tournament Manager")

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(auth_router)
app.include_router(admin_router)


@app.exception_handler(NotAuthenticatedException)
async def not_authenticated_handler(request: Request, exc: NotAuthenticatedException):
    return RedirectResponse("/login", status_code=303)


@app.on_event("startup")
def on_startup():
    create_tables()


@app.get("/health")
def health():
    return {"status": "ok"}
