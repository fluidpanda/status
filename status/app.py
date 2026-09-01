import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import poller

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
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


def _crash_on_unexpected_failure(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.critical(
            "Background poll loop died unexpectedly",
            exc_info=exc,
        )
        os._exit(1)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(poller.background_loop())
    task.add_done_callback(_crash_on_unexpected_failure)
    try:
        yield
    finally:
        task.cancel()
