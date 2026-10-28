from fastapi import FastAPI

app = FastAPI(title="Order Service")
ORDERS = [{"id": "o1", "user_id": "1", "product": "Keyboard", "total": 500000},
          {"id": "o2", "user_id": "1", "product": "Mouse", "total": 200000}]

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/orders")
def get_orders(user_id: str):
    return [order for order in ORDERS if order["user_id"] == user_id]
