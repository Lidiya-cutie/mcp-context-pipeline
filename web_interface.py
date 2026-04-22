"""
Веб-интерфейс для MCP Context Pipeline
FastAPI сервер с веб-панелью управления
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path

from fastapi import FastAPI, Request, Form, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import uvicorn

from src.host_orchestrator import ContextOrchestrator
from src.pii_guard import get_pii_guard

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="MCP Context Pipeline UI", version="1.0.0")

templates_dir = Path(__file__).parent / "templates"
static_dir = Path(__file__).parent / "static"

templates_dir.mkdir(exist_ok=True)
static_dir.mkdir(exist_ok=True)

templates = Jinja2Templates(directory=str(templates_dir))

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

orchestrator = None
pii_guard = get_pii_guard()

sessions: Dict[str, Dict] = {}
logs: List[Dict] = []


class MessageRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class CompressionRequest(BaseModel):
    threshold: Optional[int] = None


class PIIRequest(BaseModel):
    text: str
    language: str = "ru"


class Context7Request(BaseModel):
    library: str
    query: str


class KnowledgeRequest(BaseModel):
    domain: str
    topic: Optional[str] = None


@app.on_event("startup")
async def startup_event():
    global orchestrator
    logger.info("Starting MCP Context Pipeline UI")
    orchestrator = ContextOrchestrator()
    add_log("INFO", "Web interface started")


@app.on_event("shutdown")
async def shutdown_event():
    global orchestrator
    if orchestrator and orchestrator.connected:
        await orchestrator.disconnect()
    add_log("INFO", "Web interface stopped")


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "title": "MCP Context Pipeline"
    })


@app.get("/api/status")
async def get_status():
    return JSONResponse({
        "orchestrator_connected": orchestrator.connected if orchestrator else False,
        "session_count": len(sessions),
        "log_count": len(logs),
        "timestamp": datetime.now().isoformat()
    })


@app.get("/api/stats")
async def get_stats():
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    return JSONResponse({
        "session_id": orchestrator.session_id,
        "context_length": len(orchestrator.context_history),
        "compression_count": orchestrator.compression_count,
        "max_tokens": orchestrator.max_tokens,
        "summary_threshold": orchestrator.summary_threshold,
        "connected": orchestrator.connected
    })


@app.get("/api/sessions")
async def list_sessions():
    return JSONResponse({
        "sessions": list(sessions.keys())
    })


@app.post("/api/sessions/create")
async def create_session():
    session_id = f"sess_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    sessions[session_id] = {
        "created_at": datetime.now().isoformat(),
        "messages": [],
        "tokens": 0
    }
    add_log("INFO", f"Session created: {session_id}")
    return JSONResponse({"session_id": session_id})


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return JSONResponse(sessions[session_id])


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    del sessions[session_id]
    add_log("INFO", f"Session deleted: {session_id}")
    return JSONResponse({"status": "deleted"})


@app.post("/api/message")
async def send_message(request_data: MessageRequest):
    if not orchestrator or not orchestrator.connected:
        raise HTTPException(status_code=503, detail="Orchestrator not connected")

    session_id = request_data.session_id or "default"
    if session_id not in sessions:
        sessions[session_id] = {
            "created_at": datetime.now().isoformat(),
            "messages": [],
            "tokens": 0
        }

    message = {
        "role": "user",
        "content": request_data.message,
        "timestamp": datetime.now().isoformat()
    }

    sessions[session_id]["messages"].append(message)

    response_content = f"Ответ на: {request_data.message}"

    response = {
        "role": "assistant",
        "content": response_content,
        "timestamp": datetime.now().isoformat()
    }

    sessions[session_id]["messages"].append(response)

    add_log("INFO", f"Message sent in session {session_id}")

    return JSONResponse({
        "response": response_content,
        "session_id": session_id
    })


@app.post("/api/compress")
async def compress_context(request_data: CompressionRequest):
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    threshold = request_data.threshold or orchestrator.summary_threshold

    add_log("INFO", f"Compression triggered with threshold {threshold}")

    return JSONResponse({
        "status": "compressed",
        "threshold": threshold,
        "timestamp": datetime.now().isoformat()
    })


@app.post("/api/checkpoint/create")
async def create_checkpoint():
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    checkpoint_id = f"ckpt_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    add_log("INFO", f"Checkpoint created: {checkpoint_id}")

    return JSONResponse({
        "checkpoint_id": checkpoint_id,
        "timestamp": datetime.now().isoformat()
    })


@app.post("/api/pii/mask")
async def mask_pii(request_data: PIIRequest):
    masked = pii_guard.mask(request_data.text, language=request_data.language)
    entities = pii_guard.analyze(request_data.text, language=request_data.language)

    add_log("INFO", f"PII masking performed, found {len(entities)} entities")

    return JSONResponse({
        "original": request_data.text,
        "masked": masked,
        "entities": [
            {
                "type": e.entity_type,
                "text": e.text,
                "start": e.start,
                "end": e.end
            }
            for e in entities
        ]
    })


@app.post("/api/context7/query")
async def query_context7(request_data: Context7Request):
    if not orchestrator or not orchestrator.enable_context7:
        raise HTTPException(status_code=503, detail="Context7 not enabled")

    add_log("INFO", f"Context7 query: {request_data.library} - {request_data.query}")

    return JSONResponse({
        "library": request_data.library,
        "query": request_data.query,
        "result": f"Результат запроса документации для {request_data.library}",
        "timestamp": datetime.now().isoformat()
    })


@app.post("/api/knowledge/search")
async def search_knowledge(request_data: KnowledgeRequest):
    if not orchestrator or not orchestrator.enable_knowledge_bridge:
        raise HTTPException(status_code=503, detail="Knowledge Bridge not enabled")

    add_log("INFO", f"Knowledge search: {request_data.domain} - {request_data.topic}")

    return JSONResponse({
        "domain": request_data.domain,
        "topic": request_data.topic,
        "result": f"Результат поиска в Knowledge Bridge для {request_data.domain}",
        "timestamp": datetime.now().isoformat()
    })


@app.get("/api/logs")
async def get_logs(limit: int = 100):
    return JSONResponse({
        "logs": logs[-limit:] if logs else []
    })


@app.get("/api/external/metrics")
async def get_external_metrics():
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    return JSONResponse(orchestrator.get_external_knowledge_metrics())


@app.get("/api/external/metrics/history")
async def get_external_metrics_history(limit: int = 100):
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    payload = await orchestrator.get_external_knowledge_metrics_history(limit=limit)
    return JSONResponse(payload)


@app.get("/api/external/metrics/export")
async def export_external_metrics(format: str = "json", history_limit: int = 100):
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    payload = await orchestrator.export_external_knowledge_metrics(
        export_format=format,
        history_limit=history_limit
    )
    if format == "prometheus" and payload.get("status") == "ok":
        return HTMLResponse(content=payload.get("payload", ""), status_code=200)
    return JSONResponse(payload)


@app.get("/api/external/alerts")
async def get_external_alerts():
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    return JSONResponse(orchestrator.get_external_knowledge_alerts())


@app.get("/api/external/provider-health")
async def get_external_provider_health():
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    payload = await orchestrator.get_external_provider_health()
    return JSONResponse(payload)


@app.get("/context", response_class=HTMLResponse)
async def context_page(request: Request):
    return templates.TemplateResponse("context.html", {
        "request": request,
        "title": "Управление контекстом"
    })


@app.get("/pii", response_class=HTMLResponse)
async def pii_page(request: Request):
    return templates.TemplateResponse("pii.html", {
        "request": request,
        "title": "PII Маскирование"
    })


@app.get("/knowledge", response_class=HTMLResponse)
async def knowledge_page(request: Request):
    return templates.TemplateResponse("knowledge.html", {
        "request": request,
        "title": "Knowledge Bridge"
    })


@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    return templates.TemplateResponse("logs.html", {
        "request": request,
        "title": "Логи"
    })


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_json({
                "type": "update",
                "data": data,
                "timestamp": datetime.now().isoformat()
            })
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")


def add_log(level: str, message: str):
    logs.append({
        "level": level,
        "message": message,
        "timestamp": datetime.now().isoformat()
    })
    logger.info(f"[{level}] {message}")


def run_server(host: str = "0.0.0.0", port: int = 8000):
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_server()
