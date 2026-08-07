from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from glanceflow import __version__
from glanceflow.application.glanceflow_service import GlanceFlowSessionService
from glanceflow.application.scheduling_service import TrustedSchedulingService
from glanceflow.calendar.memory_provider import MemoryCalendarProvider
from glanceflow.demo.api import build_demo_router
from glanceflow.demo.controller import CompetitionDemoController
from glanceflow.simulator.api import build_router
from glanceflow.wearable.capture import FileVideoCaptureProvider
from glanceflow.wearable.frame_selection import DeterministicFrameSelector
from glanceflow.wearable.motion import ManualMotionProvider


STATIC_DIR = Path(__file__).with_name("static")
DEMO_DATA_DIR = Path(__file__).resolve().parents[3] / "data"


def create_default_service() -> GlanceFlowSessionService:
    return GlanceFlowSessionService(
        capture_provider=FileVideoCaptureProvider(),
        frame_selector=DeterministicFrameSelector(),
        motion_provider=ManualMotionProvider(),
        scheduling_service=TrustedSchedulingService(MemoryCalendarProvider()),
    )


def create_app(service: GlanceFlowSessionService | None = None) -> FastAPI:
    instance = service or create_default_service()
    app = FastAPI(title="见程 GlanceFlow 本地眼镜交互模拟器", version=__version__)
    app.state.glanceflow_service = instance
    app.state.competition_demo = CompetitionDemoController()
    app.include_router(build_router(instance, Path("work") / "uploads"))
    app.include_router(build_demo_router(app.state.competition_demo))
    app.mount("/data", StaticFiles(directory=DEMO_DATA_DIR), name="demo-assets")
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="simulator")
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("glanceflow.simulator.app:app", host="127.0.0.1", port=8765, reload=False)
