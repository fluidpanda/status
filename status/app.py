import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates

from . import poller

from fastapi.staticfiles import StaticFiles

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(poller.background_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


@app.get("/")
async def index(request: Request):
    snapshot = poller.get_snapshot()
    return templates.TemplateResponse(
        request, "index.html", {"snapshot": snapshot}
    )


@app.get("/fragment/status")
async def status_fragment(request: Request):
    snapshot = poller.get_snapshot()
    return templates.TemplateResponse(
        request, "_status_fragment.html", {"snapshot": snapshot}
    )


@app.post("/fragment/status/refresh")
async def status_refresh(request: Request):
    snapshot = await poller.refresh()
    return templates.TemplateResponse(
        request, "_status_fragment.html", {"snapshot": snapshot}
    )
