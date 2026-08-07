from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from glanceflow.demo.controller import CompetitionDemoController


class ActionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str | None = None
    fault: str | None = None


def build_demo_router(controller: CompetitionDemoController) -> APIRouter:
    router = APIRouter(prefix="/api/demo")

    @router.get("/scenarios")
    def scenarios(): return {"scenarios": controller.list_scenarios()}

    @router.post("/load")
    def load(body: ActionBody):
        try: return controller.load_scenario(body.scenario_id or "")
        except KeyError as exc: raise HTTPException(404, "unknown demo scenario") from exc

    @router.post("/step")
    def step(): return controller.run_step()

    @router.post("/auto")
    def auto(): return controller.run_auto()

    @router.post("/reset")
    def reset(): return controller.reset_scenario()

    @router.post("/fault")
    def fault(body: ActionBody): return controller.inject_fault(body.fault or "")

    @router.get("/status")
    def status(): return controller.get_status()

    return router
