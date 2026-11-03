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

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/users")
@app.get("/users/{user_id}")
async def get_user(request: Request, user_id: str | None = None):
    from urllib.parse import quote

    subject = request.state.user_id
    if user_id is not None and user_id != subject:
        raise HTTPException(403, "Access denied")
    response = await fetch(request, f"{USER_URL}/users/{quote(subject, safe='')}")
    return Response(content=response.content, status_code=response.status_code,
                    media_type="application/json")


@app.get("/orders")
async def get_orders(request: Request):
    response = await fetch(request, f"{ORDER_URL}/orders",
                           {"user_id": request.state.user_id})
    return Response(content=response.content, status_code=response.status_code,
                    media_type="application/json")



@app.get("/dashboard")
async def dashboard(request: Request):
    from urllib.parse import quote

    subject = request.state.user_id
    user_response, order_response = await asyncio.gather(
        fetch(request, f"{USER_URL}/users/{quote(subject, safe='')}"),
        fetch(request, f"{ORDER_URL}/orders", {"user_id": subject}))
    for response in (user_response, order_response):
        if response.status_code != 200:
            raise HTTPException(404 if response.status_code == 404 else 502,
                                "Unable to aggregate upstream response")
    try:
        user_data, order_data = user_response.json(), order_response.json()
    except ValueError:
        raise HTTPException(502, "Invalid upstream JSON")
    if not isinstance(user_data, dict) or not isinstance(order_data, list):
        raise HTTPException(502, "Invalid upstream response shape")
    return {"user": user_data, "orders": order_data}


class AvatarRequest(BaseModel):
    content_type: str = "image/png"



@app.post("/users/me/avatar-upload-url")
def avatar_upload_url(body: AvatarRequest, request: Request):
    from urllib.parse import quote

    extensions = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
    if body.content_type not in extensions:
        raise HTTPException(400, "Only PNG, JPEG and WebP supported")
    key = f"avatars/{quote(request.state.user_id, safe='')}/{uuid4()}.{extensions[body.content_type]}"
    client = boto3.client(
        "s3", endpoint_url=os.getenv("MINIO_PUBLIC_URL", "http://localhost:9000"),
        aws_access_key_id=os.getenv("MINIO_ROOT_USER", "minioadmin"),
        aws_secret_access_key=os.getenv("MINIO_ROOT_PASSWORD", "minioadmin123"),
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}))
    try:
        url = client.generate_presigned_url(
            "put_object", Params={"Bucket": os.getenv("MINIO_BUCKET", "avatars"),
                                  "Key": key, "ContentType": body.content_type},
            ExpiresIn=300)
    finally:
        client.close()
    return {"upload_url": url, "object_key": key, "expires_in": 300,
            "method": "PUT", "headers": {"Content-Type": body.content_type}}
