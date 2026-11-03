import json
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from issue_token import create_token



import argparse
import base64
import os
from urllib.parse import parse_qs, urlsplit

parser = argparse.ArgumentParser(description="Verify the API Gateway assignment")
parser.add_argument("--skip-storage", action="store_true",
                    help="Skip actual MinIO PUT; still validate URL generation")
args = parser.parse_args()
BASE = "http://localhost:8080"
TOKEN = create_token()


def require(condition, message):
    if not condition:
        raise RuntimeError("FAIL: " + message)
    print("PASS: " + message)


def call(path, token=TOKEN, data=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(BASE + path, headers=headers,
                      data=None if data is None else json.dumps(data).encode())
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, json.load(response), response.headers
    except HTTPError as error:
        return error.code, json.load(error), error.headers


for base in ("http://localhost:8001", "http://localhost:8002", BASE):
    with urlopen(base + "/health", timeout=10) as response:
        require(response.status == 200, "health: " + base)

time.sleep(1.1)
require(call("/users", token=None)[0] == 401, "missing JWT rejected")
require(call("/users", token="invalid")[0] == 401, "invalid JWT rejected")


import hashlib
import hmac

def expired_token():
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=")
    now = int(time.time())
    payload = encode({"alg": "HS256", "typ": "JWT"}) + b"." + encode(
        {"sub": "1", "iat": now - 120, "exp": now - 60,
         "iss": "gateway-lab", "aud": "gateway-lab"})
    secret = os.getenv("JWT_SECRET", "local-demo-change-this-secret-at-least-32-characters")
    signature = base64.urlsafe_b64encode(
        hmac.new(secret.encode(), payload, hashlib.sha256).digest()).rstrip(b"=")
    return (payload + b"." + signature).decode()

require(call("/users", token=expired_token())[0] == 401, "expired JWT rejected")
status, user, _ = call("/users")
require(status == 200 and user.get("id") == "1", "/users routing")
require(call("/users/2")[0] == 403, "cross-user access denied")
require(call("/users", token=create_token("missing"))[0] == 404, "upstream 404 preserved")
status, orders, _ = call("/orders?user_id=2")
require(status == 200 and len(orders) == 2 and all(order["user_id"] == "1" for order in orders),
        "/orders routing uses the JWT subject")
status, dashboard, _ = call("/dashboard")
require(status == 200 and dashboard.get("user") == user and dashboard.get("orders") == orders,
        "/dashboard aggregates the user's own data")

time.sleep(1.1)
require(call("/users/me/avatar-upload-url", data={"content_type": "text/plain"})[0] == 400,
        "unsupported avatar type rejected")
status, upload, _ = call("/users/me/avatar-upload-url", data={"content_type": "image/png"})
require(status == 200 and upload.get("expires_in") == 300 and upload.get("method") == "PUT",
        "avatar URL response")
query = parse_qs(urlsplit(upload["upload_url"]).query)
require(query.get("X-Amz-Expires") == ["300"] and "X-Amz-Signature" in query,
        "signed URL expires after 5 minutes")
require("content-type" in query.get("X-Amz-SignedHeaders", [""])[0],
        "upload content type is signed")
png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aN1cAAAAASUVORK5CYII=")
if args.skip_storage:
    print("SKIP: actual MinIO PUT (--skip-storage); storage is not verified")
else:
    with urlopen(Request(upload["upload_url"], data=png, method="PUT", headers=upload["headers"]), timeout=10) as response:
        require(response.status == 200, "actual upload directly to MinIO")

time.sleep(1.1)
responses = [call("/users") for _ in range(11)]
statuses = [response[0] for response in responses]
require(statuses[:10] == [200] * 10 and statuses[10] == 429,
        "10 requests per second: " + str(statuses))
require(responses[10][2].get("Retry-After") == "1", "rate-limit Retry-After header")
time.sleep(1.1)
require(call("/users")[0] == 200, "requests recover after the rate-limit window")
print("Run scripts/benchmark.py separately to measure direct versus gateway latency.")
