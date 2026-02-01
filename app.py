import os
import json
import uuid
from datetime import datetime, timezone
from collections import deque
from typing import Any, Dict, List, Optional
from urllib import request as urlrequest


from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI()

# -----------------------
# Config
# -----------------------
MAX_EVENTS = int(os.getenv("MAX_EVENTS", "50"))
MAX_BODY_BYTES = int(os.getenv("MAX_BODY_BYTES", "262144"))  # 256 KB
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "").strip()  # optional (recommended)

# Upstash / Vercel KV env vars (either naming style)
UPSTASH_REST_URL = (os.getenv("UPSTASH_REDIS_REST_URL") or os.getenv("KV_REST_API_URL") or "").strip()
UPSTASH_REST_TOKEN = (os.getenv("UPSTASH_REDIS_REST_TOKEN") or os.getenv("KV_REST_API_TOKEN") or "").strip()
USE_UPSTASH = bool(UPSTASH_REST_URL and UPSTASH_REST_TOKEN)

REDIS_LIST_KEY = os.getenv("REDIS_LIST_KEY", "webhook:events")

# Memory fallback (works locally and sometimes on warm instances, but not guaranteed on Vercel)
_memory_events = deque(maxlen=MAX_EVENTS)


# -----------------------
# Helpers
# -----------------------
def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _client_ip(req: Request) -> str:
    # Vercel usually forwards real IP in these headers
    xff = req.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    real_ip = req.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return req.client.host if req.client else "unknown"

def _important_headers(req: Request) -> Dict[str, str]:
    keep = [
        "content-type",
        "user-agent",
        "x-forwarded-for",
        "x-real-ip",
        "x-vercel-id",
        "x-vercel-ip-country",
        "x-vercel-ip-city",
        "x-vercel-ip-region",
    ]
    out = {}
    for k in keep:
        v = req.headers.get(k)
        if v:
            out[k] = v
    return out

def _pretty_body(parsed: Any) -> str:
    if isinstance(parsed, (dict, list)):
        return json.dumps(parsed, indent=2, ensure_ascii=False)
    return str(parsed)

def _upstash_cmd(args: List[Any]) -> Any:
    """
    Upstash REST API supports sending the entire command as a JSON array in POST body:
    e.g. ["LPUSH","key","value"]
    """
    if not USE_UPSTASH:
        raise RuntimeError("Upstash not configured")

    data = json.dumps(args).encode("utf-8")
    req = urlrequest.Request(
        UPSTASH_REST_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {UPSTASH_REST_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlrequest.urlopen(req, timeout=10) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if "error" in payload and payload["error"]:
        raise RuntimeError(payload["error"])
    return payload.get("result")

def _store_event(event: Dict[str, Any]) -> None:
    if USE_UPSTASH:
        s = json.dumps(event, ensure_ascii=False)
        _upstash_cmd(["LPUSH", REDIS_LIST_KEY, s])
        _upstash_cmd(["LTRIM", REDIS_LIST_KEY, 0, MAX_EVENTS - 1])
    else:
        _memory_events.appendleft(event)

def _load_events(limit: int) -> List[Dict[str, Any]]:
    limit = max(1, min(limit, 100))
    if USE_UPSTASH:
        raw = _upstash_cmd(["LRANGE", REDIS_LIST_KEY, 0, limit - 1]) or []
        out = []
        for item in raw:
            try:
                out.append(json.loads(item))
            except Exception:
                out.append({"id": "bad", "received_at": _utc_now_iso(), "body_pretty": str(item)})
        return out
    return list(_memory_events)[:limit]

def _check_token(req: Request) -> None:
    if not WEBHOOK_TOKEN:
        return
    provided = (req.headers.get("x-webhook-token") or req.query_params.get("token") or "").strip()
    if provided != WEBHOOK_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid webhook token")


# -----------------------
# Routes
# -----------------------
@app.get("/api/info")
async def info():
    return {
        "status": "ok",
        "storage": "upstash" if USE_UPSTASH else "memory",
        "max_events": MAX_EVENTS,
        "token_required": bool(WEBHOOK_TOKEN),
    }

@app.get("/api/events")
async def events(limit: int = 30):
    return {"events": _load_events(limit)}

@app.post("/api/webhook")
async def webhook(req: Request):
    _check_token(req)

    body = await req.body()
    truncated = False
    if len(body) > MAX_BODY_BYTES:
        body = body[:MAX_BODY_BYTES]
        truncated = True

    content_type = (req.headers.get("content-type") or "").lower()

    parsed: Any
    raw_text: str

    # Try JSON first if it looks like JSON
    raw_text = body.decode("utf-8", errors="replace")
    parsed = raw_text
    if "application/json" in content_type or raw_text.lstrip().startswith(("{", "[")):
        try:
            parsed = json.loads(raw_text)
        except Exception:
            parsed = raw_text

    event = {
        "id": uuid.uuid4().hex,
        "received_at": _utc_now_iso(),
        "ip": _client_ip(req),
        "content_type": content_type or "unknown",
        "headers": _important_headers(req),
        "truncated": truncated,
        "bytes": len(body),
        "body_pretty": _pretty_body(parsed),
    }

    _store_event(event)
    return JSONResponse({"status": "ok", "id": event["id"]})
