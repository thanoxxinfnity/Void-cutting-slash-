"""Void Cutting Slash — master FastAPI server.

Serves the dashboard, routes chat messages between the fast_chat engine and
the heavy 5-tier swarm cascade, manages BYOK settings, exposes project
history, and triggers Vercel deployments of swarm output.
"""
import json
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from agents import fast_chat, router, vercel_deployer
from agents.nvidia_client import NvidiaAPIError, list_models
from agents.swarm_engine import load_project, run_swarm, set_project_vercel_url
from agents.vercel_deployer import VercelDeployError

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config" / "settings.json"
HISTORY_PATH = BASE_DIR / "data" / "projects_history.json"

app = FastAPI(title="Void Cutting Slash")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

DEFAULT_SETTINGS = {
    "nvidia_api_key": "",
    "vercel_token": "",
    "cloud_terminal_url": "",
    # Model IDs that were verified to actually respond (HTTP 200) for a real
    # BYOK trial key against integrate.api.nvidia.com/v1/chat/completions.
    # The full NVIDIA catalog lists more (e.g. moonshotai/kimi-k2.6,
    # deepseek-ai/deepseek-coder-6.7b-instruct) but many require account-level
    # entitlements and 404 on a fresh key — swap these in Settings once your
    # account has access to them.
    "models": {
        "fast_chat": "meta/llama-3.1-8b-instruct",
        "generator": "deepseek-ai/deepseek-v4-flash-0731",
        "auditor": "z-ai/glm-5.2",
        "deep_reasoner": "nvidia/nemotron-3-ultra-550b-a55b",
        "syntax_verifier": "meta/llama-3.1-8b-instruct",
        "safety_net": "z-ai/glm-5.2",
    },
    "max_audit_loops": 3,
}


def _read_persisted_settings() -> dict:
    """Settings as they exist on disk only — never includes env-var
    overrides. This is the base used whenever we're about to WRITE the file,
    so an env-sourced key can never leak into the tracked JSON."""
    settings = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
    merged = {**DEFAULT_SETTINGS, **settings}
    merged["models"] = {**DEFAULT_SETTINGS["models"], **settings.get("models", {})}
    return merged


def load_settings() -> dict:
    """Settings for runtime use (calling NVIDIA/Vercel). Environment
    variables always win over the file, so a real key never has to be
    written to disk to be used."""
    merged = _read_persisted_settings()
    if os.environ.get("NVIDIA_API_KEY"):
        merged["nvidia_api_key"] = os.environ["NVIDIA_API_KEY"]
    if os.environ.get("VERCEL_TOKEN"):
        merged["vercel_token"] = os.environ["VERCEL_TOKEN"]
    return merged


def save_settings(settings: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(settings, indent=2))


def _mask(key: str) -> str:
    if not key:
        return ""
    return key[:6] + "…" + key[-4:] if len(key) > 12 else "•" * len(key)


class SettingsIn(BaseModel):
    nvidia_api_key: Optional[str] = None
    vercel_token: Optional[str] = None
    cloud_terminal_url: Optional[str] = None
    models: Optional[dict] = None
    max_audit_loops: Optional[int] = None


class ChatIn(BaseModel):
    message: str
    history: list = []
    mode: Optional[str] = None  # "fast" | "heavy" | None (auto)


class DeployIn(BaseModel):
    project_id: str
    project_name: Optional[str] = None


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/settings")
async def get_settings():
    settings = load_settings()
    return {**settings, "nvidia_api_key": _mask(settings["nvidia_api_key"]),
            "vercel_token": _mask(settings["vercel_token"])}


@app.post("/api/settings")
async def update_settings(body: SettingsIn):
    settings = _read_persisted_settings()
    data = body.model_dump(exclude_unset=True)

    verified = None
    if "nvidia_api_key" in data and data["nvidia_api_key"]:
        try:
            models = list_models(data["nvidia_api_key"])
            verified = {"ok": True, "model_count": len(models)}
        except NvidiaAPIError as exc:
            raise HTTPException(status_code=400, detail=f"NVIDIA key rejected: {exc}") from exc

    for field in ("nvidia_api_key", "vercel_token", "cloud_terminal_url", "max_audit_loops"):
        if data.get(field) is not None:
            settings[field] = data[field]
    if data.get("models"):
        settings["models"] = {**settings["models"], **data["models"]}

    save_settings(settings)
    resp = {**settings, "nvidia_api_key": _mask(settings["nvidia_api_key"]),
            "vercel_token": _mask(settings["vercel_token"])}
    if verified:
        resp["nvidia_key_verified"] = verified
    return resp


@app.get("/api/history")
async def get_history():
    if not HISTORY_PATH.exists():
        return []
    return json.loads(HISTORY_PATH.read_text())


@app.get("/api/history/{project_id}")
async def get_history_item(project_id: str):
    project = load_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.post("/api/chat")
async def chat(body: ChatIn):
    settings = load_settings()
    if not settings.get("nvidia_api_key"):
        raise HTTPException(status_code=400, detail="Add your NVIDIA API key in Settings first.")

    intent = router.classify_intent(body.message, force_mode=body.mode)

    def event(kind: str, data: dict) -> str:
        return f"event: {kind}\ndata: {json.dumps(data)}\n\n"

    def sse_stream():
        yield event("intent", {"mode": intent})
        try:
            if intent == router.FAST:
                model = settings["models"]["fast_chat"]
                for token in fast_chat.run_fast_chat(
                    settings["nvidia_api_key"], model, body.message, body.history, stream=True
                ):
                    yield event("token", {"token": token})
                yield event("done", {"mode": "fast"})
            else:
                def on_tier_event(e):
                    pass  # collected via generator below; SSE needs synchronous yields

                # run_swarm is synchronous; we drive it tier-by-tier and push
                # each progress event out over SSE as it happens.
                events = []
                result = run_swarm(settings, body.message, on_event=events.append)
                for e in events:
                    yield event("tier", e)
                yield event("result", {
                    "id": result["id"],
                    "files": result["files"],
                })
                yield event("done", {"mode": "heavy"})
        except NvidiaAPIError as exc:
            yield event("error", {"message": str(exc)})

    return StreamingResponse(sse_stream(), media_type="text/event-stream")


@app.post("/api/deploy")
async def deploy(body: DeployIn):
    settings = load_settings()
    if not settings.get("vercel_token"):
        raise HTTPException(status_code=400, detail="Add your Vercel token in Settings first.")

    project = load_project(body.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        result = vercel_deployer.deploy_files(
            settings["vercel_token"],
            body.project_name or project["prompt"][:40],
            project["files"],
        )
    except VercelDeployError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if result.get("url"):
        set_project_vercel_url(body.project_id, result["url"])
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
