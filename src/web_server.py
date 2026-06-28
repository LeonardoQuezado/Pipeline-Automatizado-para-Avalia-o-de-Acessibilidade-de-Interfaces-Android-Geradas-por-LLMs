"""Web interface for the Accessibility LLM Pipeline.

Runs automatically via docker-compose.
Access at: http://localhost:8000
"""
import asyncio
import os
import sys
from pathlib import Path

import json

import aiohttp
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

REPORTS_DIR = Path("/app/outputs/reports")

sys.path.insert(0, str(Path(__file__).parent))

PROMPTS_DIR       = Path("/app/prompts")
TEMPLATES_DIR     = Path(__file__).parent / "templates"
VALIDATION_DIR    = Path(__file__).parent / "validation_screens"

_VALIDATION_META = {
    "ProfileScreen":      "3 IN · 2 TF (LINT) + ST (ATF)",
    "GalleryGridScreen":  "1 IN (LINT) · 16 ST · 0 TT (ATF)",
    "SettingsFormScreen": "4 TF · 2 IN (LINT) + ST (ATF)",
}

app = FastAPI(title="Accessibility LLM Pipeline")

_pipeline_lock = asyncio.Lock()
_current_process: asyncio.subprocess.Process | None = None


# ── Models ────────────────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    prompt: str
    selected_llms: list[str] = []
    few_shot_examples: str = ""
    n_runs: int = 1
    self_repair: bool = False


class TestRunRequest(BaseModel):
    kotlin_code: str


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse((TEMPLATES_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/teste", response_class=HTMLResponse)
async def teste():
    return HTMLResponse((TEMPLATES_DIR / "teste.html").read_text(encoding="utf-8"))


@app.get("/api/validation-screens")
async def validation_screens():
    if not VALIDATION_DIR.exists():
        return JSONResponse({"screens": []})
    screens = []
    for f in sorted(VALIDATION_DIR.glob("*.kt")):
        screens.append({
            "id": f.stem,
            "name": f.stem,
            "expected": _VALIDATION_META.get(f.stem, ""),
            "code": f.read_text(encoding="utf-8"),
        })
    return JSONResponse({"screens": screens})


@app.post("/api/test-run")
async def test_run(body: TestRunRequest):
    if _pipeline_lock.locked():
        raise HTTPException(status_code=409, detail="Pipeline já em execução")

    async def generate():
        global _current_process
        async with _pipeline_lock:
            PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
            (PROMPTS_DIR / "test_code.kt").write_text(body.kotlin_code, encoding="utf-8")

            env = {**os.environ, "PYTHONUNBUFFERED": "1"}
            _current_process = await asyncio.create_subprocess_exec(
                sys.executable, "-u", "/app/src/test_run.py",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
            try:
                while True:
                    try:
                        line = await asyncio.wait_for(
                            _current_process.stdout.readline(), timeout=25.0
                        )
                    except asyncio.TimeoutError:
                        yield ": heartbeat\n\n"
                        continue
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace").rstrip()
                    yield f"data: {text}\n\n"
                await _current_process.wait()
            finally:
                _current_process = None

            yield "data: __DONE__\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _ping_ollama() -> bool:
    """Tenta alcançar o servidor Ollama local com timeout de 2 s."""
    base = os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
    try:
        timeout = aiohttp.ClientTimeout(total=2)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{base}/api/tags") as resp:
                return resp.status == 200
    except Exception:
        return False


@app.get("/api/status")
async def get_status():
    ollama_ok = await _ping_ollama()
    return {
        "running": _pipeline_lock.locked(),
        "llms": {
            "gemini":    bool(os.environ.get("GEMINI_API_KEY")),
            "groq":      bool(os.environ.get("GROQ_API_KEY")),
            "deepseek":  bool(os.environ.get("DEEPSEEK_API_KEY")),
            "xai":       bool(os.environ.get("XAI_API_KEY")),
            "openai":    bool(os.environ.get("OPENAI_API_KEY")),
            "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "ollama":    ollama_ok,
        },
    }


@app.get("/api/report/latest")
async def get_latest_report():
    if not REPORTS_DIR.exists():
        raise HTTPException(status_code=404, detail="No reports yet")
    files = sorted(REPORTS_DIR.glob("report_*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise HTTPException(status_code=404, detail="No reports yet")
    return JSONResponse(json.loads(files[-1].read_text(encoding="utf-8")))


@app.get("/api/prompts")
async def list_prompts():
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(p.name for p in PROMPTS_DIR.glob("*.txt"))
    return {"prompts": files}


@app.get("/api/prompts/{name}")
async def get_prompt(name: str):
    if "/" in name or ".." in name:
        raise HTTPException(status_code=400, detail="Invalid file name")
    path = PROMPTS_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Prompt not found")
    return {"name": name, "content": path.read_text(encoding="utf-8")}


@app.post("/api/run")
async def run_pipeline(body: RunRequest):
    if _pipeline_lock.locked():
        raise HTTPException(status_code=409, detail="Pipeline already running")

    async def generate():
        global _current_process
        async with _pipeline_lock:
            PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
            (PROMPTS_DIR / "prompt.txt").write_text(body.prompt, encoding="utf-8")
            few_shot_file = PROMPTS_DIR / "few_shot_examples.txt"
            if body.few_shot_examples.strip():
                few_shot_file.write_text(body.few_shot_examples, encoding="utf-8")
            elif few_shot_file.exists():
                few_shot_file.unlink()

            env = {**os.environ, "PYTHONUNBUFFERED": "1"}
            if body.selected_llms:
                env["ENABLED_LLMS"] = ",".join(body.selected_llms)
            env["N_RUNS"] = str(max(1, min(body.n_runs, 10)))
            if body.self_repair:
                env["SELF_REPAIR"] = "true"
            _current_process = await asyncio.create_subprocess_exec(
                sys.executable, "-u", "/app/src/pipeline.py",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
            try:
                while True:
                    try:
                        line = await asyncio.wait_for(
                            _current_process.stdout.readline(), timeout=25.0
                        )
                    except asyncio.TimeoutError:
                        yield ": heartbeat\n\n"
                        continue
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace").rstrip()
                    yield f"data: {text}\n\n"
                await _current_process.wait()
            finally:
                _current_process = None

            yield "data: __DONE__\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
