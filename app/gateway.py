import asyncio
import math
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from uuid import uuid4

import boto3
import httpx
import jwt
from botocore.config import Config
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

SECRET = os.getenv("JWT_SECRET", "local-demo-change-this-secret-at-least-32-characters")
USER_URL = os.getenv("USER_URL", "http://localhost:8001")
ORDER_URL = os.getenv("ORDER_URL", "http://localhost:8002")

@asynccontextmanager
async def lifespan(app):
    async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
        app.state.client = client
        yield

app = FastAPI(title="API Gateway Lab", lifespan=lifespan)
windows = {}

@app.middleware("http")
async def policy(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)
    now = time.monotonic()
   
    for key in list(windows):
        if not windows[key] or now - windows[key][-1] >= 1:
            del windows[key]
    ip = request.client.host if request.client else "unknown"
    queue = windows.setdefault(ip, deque())
    while queue and now - queue[0] >= 1:
        queue.popleft()
    if len(queue) >= 10:
        return JSONResponse({"detail": "Rate limit exceeded"}, 429,
                            headers={"Retry-After": str(max(1, math.ceil(1 - now + queue[0])))})
    queue.append(now)
    header = request.headers.get("authorization", "")
    try:
        scheme, token = header.split(" ", 1)
        if scheme.lower() != "bearer":
            raise ValueError("scheme")
        claims = jwt.decode(token, SECRET, algorithms=["HS256"],
                            issuer="gateway-lab", audience="gateway-lab",
                            options={"require": ["exp", "iat", "sub", "iss", "aud"]})
        if not isinstance(claims["sub"], str) or not claims["sub"]:
            raise ValueError("subject")
        request.state.user_id = claims["sub"]
    except (ValueError, jwt.PyJWTError):
        return JSONResponse({"detail": "Missing or invalid JWT"}, 401,
                            headers={"WWW-Authenticate": "Bearer"})
    return await call_next(request)

async def fetch(request, url, params=None):
    try:
        response = await request.app.state.client.get(url, params=params)
    except httpx.TimeoutException:
        raise HTTPException(504, "Upstream timeout")
    except httpx.RequestError:
        raise HTTPException(502, "Upstream unavailable")
    return response

