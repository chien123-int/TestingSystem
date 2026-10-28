from fastapi import FastAPI, HTTPException

app = FastAPI(title="User Service")
USERS = {"1": {"id": "1", "name": "Nguyen An", "email": "an@example.com"}}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/users/{user_id}")
def get_user(user_id: str):
    if user_id not in USERS:
        raise HTTPException(404, "User not found")
    return USERS[user_id]
