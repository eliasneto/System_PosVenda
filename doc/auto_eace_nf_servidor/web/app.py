import asyncio
import json
import os
import re
import shutil
from pathlib import Path

import aiosqlite
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = BASE_DIR / "input"
EACE_DIR = INPUT_DIR / "EACE"
OUTPUT_DIR = BASE_DIR / "output"
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "config.db"
OSP_FILE = INPUT_DIR / "osp.txt"

for _d in [EACE_DIR, OUTPUT_DIR, DATA_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
ALLOWED_EXT = {".pdf", ".xml"}

app = FastAPI(title="EACE RPA Portal")

_state: dict = {
    "running": False,
    "process": None,
    "logs": [],
    "queues": set(),
}


# ─── Database ────────────────────────────────────────────────────────────────

async def _init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        defaults = [
            ("eace_url", "https://eace.org.br/login?login=login"),
            ("eace_usuario", ""),
            ("eace_senha", ""),
            ("timeout_ms", "30000"),
            ("delay_ms", "1500"),
        ]
        for k, v in defaults:
            await db.execute("INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", (k, v))
        await db.commit()


async def _get_cfg() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT key, value FROM config")
        return {r["key"]: r["value"] for r in await cur.fetchall()}


@app.on_event("startup")
async def startup() -> None:
    await _init_db()


# ─── Config ──────────────────────────────────────────────────────────────────

class ConfigIn(BaseModel):
    eace_url: str
    eace_usuario: str
    eace_senha: str
    timeout_ms: str = "30000"
    delay_ms: str = "1500"


@app.get("/api/config")
async def read_config():
    return await _get_cfg()


@app.put("/api/config")
async def save_config(data: ConfigIn):
    async with aiosqlite.connect(DB_PATH) as db:
        for k, v in data.model_dump().items():
            await db.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (k, v)
            )
        await db.commit()
    return {"ok": True}


# ─── OSP ─────────────────────────────────────────────────────────────────────

@app.get("/api/osp")
async def read_osp():
    content = OSP_FILE.read_text(encoding="utf-8") if OSP_FILE.exists() else ""
    return {"content": content}


class OspIn(BaseModel):
    content: str


@app.put("/api/osp")
async def save_osp(data: OspIn):
    OSP_FILE.write_text(data.content.strip(), encoding="utf-8")
    return {"ok": True}


# ─── Files ───────────────────────────────────────────────────────────────────

def _build_tree() -> list:
    if not EACE_DIR.exists():
        return []
    result = []
    for inep_dir in sorted(EACE_DIR.iterdir()):
        if not inep_dir.is_dir():
            continue
        item: dict = {"inep": inep_dir.name, "tipos": {}}
        for tipo in ["KIT", "NOBREAK"]:
            d = inep_dir / tipo
            item["tipos"][tipo] = (
                sorted(f.name for f in d.iterdir() if f.is_file()) if d.exists() else []
            )
        result.append(item)
    return result


@app.get("/api/files")
async def list_files():
    return {"tree": _build_tree()}


@app.post("/api/files/inep/{inep}")
async def create_inep(inep: str):
    if not inep.isdigit():
        raise HTTPException(400, "INEP deve conter apenas dígitos")
    for tipo in ["KIT", "NOBREAK"]:
        (EACE_DIR / inep / tipo).mkdir(parents=True, exist_ok=True)
    return {"ok": True}


@app.delete("/api/files/inep/{inep}")
async def delete_inep(inep: str):
    d = EACE_DIR / inep
    if d.exists():
        shutil.rmtree(d)
    return {"ok": True}


@app.post("/api/files/upload/{inep}/{tipo}")
async def upload_files(inep: str, tipo: str, files: list[UploadFile] = File(...)):
    if tipo not in ("KIT", "NOBREAK"):
        raise HTTPException(400, "Tipo inválido")
    uploaded = []
    for file in files:
        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_EXT:
            raise HTTPException(400, f"Extensão não permitida: {ext}. Use .pdf ou .xml")
        dest = EACE_DIR / inep / tipo / file.filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(await file.read())
        uploaded.append(file.filename)
    return {"ok": True, "uploaded": uploaded}


@app.delete("/api/files/{inep}/{tipo}/{filename}")
async def delete_file(inep: str, tipo: str, filename: str):
    f = EACE_DIR / inep / tipo / filename
    if f.exists():
        f.unlink()
    return {"ok": True}


# ─── Execution ───────────────────────────────────────────────────────────────

async def _broadcast(line: str) -> None:
    _state["logs"].append(line)
    for q in list(_state["queues"]):
        try:
            q.put_nowait(line)
        except asyncio.QueueFull:
            pass


async def _run_rpa() -> None:
    cfg = await _get_cfg()
    env = {
        **os.environ,
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
        "NO_COLOR": "1",
        "EACE_URL": cfg.get("eace_url", ""),
        "EACE_USUARIO": cfg.get("eace_usuario", ""),
        "EACE_SENHA": cfg.get("eace_senha", ""),
        "HEADLESS": "true",
        "TIMEOUT_MS": cfg.get("timeout_ms", "30000"),
        "DELAY_MS": cfg.get("delay_ms", "1500"),
    }
    _state["logs"] = []
    await _broadcast(">>> Iniciando execução EACE RPA <<<")

    try:
        proc = await asyncio.create_subprocess_exec(
            "python", "-u", str(BASE_DIR / "src" / "main.py"),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            cwd=str(BASE_DIR),
        )
        _state["process"] = proc
        async for raw in proc.stdout:
            line = ANSI_RE.sub("", raw.decode("utf-8", errors="replace").rstrip())
            if line:
                await _broadcast(line)
        await proc.wait()
        label = "concluída com sucesso" if proc.returncode == 0 else f"encerrada com código {proc.returncode}"
        await _broadcast(f">>> Execução {label} <<<")
    except Exception as exc:
        await _broadcast(f">>> ERRO INTERNO: {exc} <<<")
    finally:
        _state["running"] = False
        _state["process"] = None
        await _broadcast("__END__")


@app.post("/api/execute")
async def execute():
    if _state["running"]:
        raise HTTPException(409, "Execução já em andamento")
    _state["running"] = True
    asyncio.create_task(_run_rpa())
    return {"ok": True}


@app.get("/api/execute/status")
async def get_status():
    return {"running": _state["running"]}


@app.get("/api/logs/stream")
async def stream_logs():
    q: asyncio.Queue = asyncio.Queue(maxsize=2000)
    for line in _state["logs"]:
        await q.put(line)
    _state["queues"].add(q)

    async def generator():
        try:
            while True:
                try:
                    line = await asyncio.wait_for(q.get(), timeout=25)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if line == "__END__":
                    yield "event: end\ndata: done\n\n"
                    break
                yield f"data: {json.dumps(line)}\n\n"
        finally:
            _state["queues"].discard(q)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─── Static frontend ─────────────────────────────────────────────────────────

app.mount("/", StaticFiles(directory=str(Path(__file__).parent / "static"), html=True))
