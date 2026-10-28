"""Local demo token issuer. Never expose as a public unauthenticated endpoint."""
import argparse
import base64
import hashlib
import hmac
import json
import os
import time

def create_token(subject="1"):
    secret = os.getenv("JWT_SECRET", "local-demo-change-this-secret-at-least-32-characters")
    def encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=")
    now = int(time.time())
    header = encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = encode(json.dumps({"sub": subject, "iat": now, "exp": now + 3600,
                              "iss": "gateway-lab", "aud": "gateway-lab"}).encode())
    payload = header + b"." + body
    return (payload + b"." + encode(hmac.new(secret.encode(), payload, hashlib.sha256).digest())).decode()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", default="1")
    print(create_token(parser.parse_args().user_id))
