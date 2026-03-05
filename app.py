from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from database import create_tables

app = FastAPI(title="BitBT – Robot Combat Tournament Manager")

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
def on_startup():
    create_tables()


@app.get("/health")
def health():
    return {"status": "ok"}
