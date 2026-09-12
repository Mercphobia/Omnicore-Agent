"""HTTP API v2 for OmniCore. FastAPI with WebSocket streaming.
Usage: uvicorn ui.api:app --host 0.0.0.0 --port 8000
"""

import json
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager

from core.engine import OmniCore
from core.error_handler import ErrorHandler, RetryConfig, ProviderFallback


# ── Application lifecycle ──────────────────────────────────

agent: OmniCore | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent
    agent = OmniCore()
    yield
    agent = None


app = FastAPI(
    title="OmniCore API",
    version="1.0.0",
    description="The All-Rounder AI Agent — REST + WebSocket API",
    lifespan=lifespan,
)


# ── Models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    model: str | None = None
    temperature: float = Field(default=0.7, ge=0, le=2.0)
    max_tokens: int = Field(default=4096, ge=1, le=32768)
    stream: bool = False


class ChatResponse(BaseModel):
    response: str
    session_id: str
    model: str
    latency_ms: float
    tokens: dict | None = None


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
    timestamp: float


class HealthResponse(BaseModel):
    status: str
    provider: str
    model: str
    version: str
    uptime_seconds: float


class SessionInfo(BaseModel):
    id: str
    title: str | None
    created_at: float
    updated_at: float
    message_count: int


# ── Middleware ─────────────────────────────────────────────

@app.middleware("http")
async def add_timing_header(request, call_next):
    t0 = time.time()
    response = await call_next(request)
    response.headers["X-Process-Time-Ms"] = f"{(time.time() - t0) * 1000:.0f}"
    return response


# ── REST endpoints ─────────────────────────────────────────

@app.post("/chat", response_model=ChatResponse, responses={500: {"model": ErrorResponse}})
async def chat(req: ChatRequest):
    """Send a message to OmniCore and get a response."""
    try:
        t0 = time.perf_counter()
        response = await agent.run(req.message)
        elapsed = (time.perf_counter() - t0) * 1000

        return ChatResponse(
            response=response,
            session_id=req.session_id,
            model=agent.provider.default_model,
            latency_ms=round(elapsed, 1),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"error": str(e), "timestamp": time.time()},
        )


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="ok",
        provider=agent.config.get("provider", {}).get("default", "?"),
        model=agent.provider.default_model,
        version="1.0.0",
        uptime_seconds=0,  # Stateless — resets per deploy
    )


@app.get("/tools")
async def list_tools():
    return {
        "count": len(agent.registry.list_all()),
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "requires_approval": t.requires_approval,
            }
            for t in agent.registry.list_all()
        ],
    }


@app.get("/sessions", response_model=list[SessionInfo])
async def list_sessions():
    sessions = agent.memory.list_sessions()
    result = []
    for s in sessions:
        msgs = agent.memory.get_messages(s["id"])
        result.append(SessionInfo(
            id=s["id"],
            title=s.get("title"),
            created_at=s.get("created_at", 0),
            updated_at=s.get("updated_at", 0),
            message_count=len(msgs),
        ))
    return result


@app.get("/sessions/{session_id}/history")
async def get_session_history(session_id: str, limit: int = 50):
    messages = agent.memory.get_messages(session_id, limit=limit)
    return {
        "session_id": session_id,
        "count": len(messages),
        "messages": messages,
    }


@app.post("/reset")
async def reset():
    agent.reset()
    return {"status": "reset", "session_id": agent.session_id}


# ── WebSocket endpoint ─────────────────────────────────────

@app.websocket("/ws")
async def websocket_chat(websocket: WebSocket):
    """Real-time chat via WebSocket with streaming support."""
    await websocket.accept()

    try:
        while True:
            data = await websocket.receive_text()
            try:
                request = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json({"error": "Invalid JSON"})
                continue

            message = request.get("message", "")
            if not message:
                await websocket.send_json({"error": "Message required"})
                continue

            stream = request.get("stream", False)

            if stream:
                # Stream response token by token
                await websocket.send_json({"type": "start", "session_id": agent.session_id})
                # TODO: actual streaming when provider supports it
                response = await agent.run(message)
                await websocket.send_json({"type": "token", "content": response})
                await websocket.send_json({"type": "end"})
            else:
                response = await agent.run(message)
                await websocket.send_json({
                    "type": "response",
                    "content": response,
                    "session_id": agent.session_id,
                })

    except WebSocketDisconnect:
        pass  # Client disconnected
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "error": str(e)})
        except Exception:
            pass


# ── Entry point ────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)