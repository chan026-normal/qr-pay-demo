import asyncio
import io
import socket
import uuid
from base64 import b64encode
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import qrcode
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

STORE_NAME = "coconut.kim"
STORE_ID = "coco-001"

app = FastAPI(title="QR Pay Demo")
templates = Jinja2Templates(directory="templates")


@dataclass
class Order:
    order_id: str
    amount: int
    memo: str
    status: str = "pending"  # pending | paid | cancelled
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    paid_at: Optional[str] = None
    payer_name: Optional[str] = None
    method: Optional[str] = None  # card | bank | point


ORDERS: Dict[str, Order] = {}
HISTORY: List[Order] = []
SUBSCRIBERS: Dict[str, List[WebSocket]] = {}


def get_lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def make_qr_data_url(url: str) -> str:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0F172A", back_color="#FFFFFF")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + b64encode(buf.getvalue()).decode()


async def broadcast(order_id: str, event: dict) -> None:
    listeners = SUBSCRIBERS.get(order_id, [])
    dead: List[WebSocket] = []
    for ws in listeners:
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        listeners.remove(ws)


@app.get("/", response_class=HTMLResponse)
async def merchant_page(request: Request):
    lan_ip = get_lan_ip()
    port = request.url.port or 8000
    return templates.TemplateResponse(
        "merchant.html",
        {
            "request": request,
            "store_name": STORE_NAME,
            "store_id": STORE_ID,
            "lan_host": f"{lan_ip}:{port}",
        },
    )


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "store_name": STORE_NAME,
            "orders": list(reversed(HISTORY))[:50],
        },
    )


@app.get("/pay/{order_id}", response_class=HTMLResponse)
async def pay_page(request: Request, order_id: str):
    order = ORDERS.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다.")
    return templates.TemplateResponse(
        "pay.html",
        {
            "request": request,
            "store_name": STORE_NAME,
            "order": order,
        },
    )


@app.post("/api/order")
async def create_order(payload: dict):
    try:
        amount = int(payload.get("amount", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="금액이 올바르지 않습니다.")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="금액은 0보다 커야 합니다.")
    memo = (payload.get("memo") or "").strip()[:40]

    order_id = uuid.uuid4().hex[:10].upper()
    order = Order(order_id=order_id, amount=amount, memo=memo)
    ORDERS[order_id] = order

    request: Request = payload.get("__request__")  # not used; client supplies base
    base = (payload.get("base") or "").rstrip("/")
    pay_url = f"{base}/pay/{order_id}" if base else f"/pay/{order_id}"
    qr_data_url = make_qr_data_url(pay_url)

    return {
        "order_id": order_id,
        "amount": amount,
        "memo": memo,
        "pay_url": pay_url,
        "qr": qr_data_url,
        "status": order.status,
    }


@app.get("/api/order/{order_id}")
async def get_order(order_id: str):
    order = ORDERS.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="주문 없음")
    return order.__dict__


@app.post("/api/order/{order_id}/pay")
async def pay_order(order_id: str, payload: dict):
    order = ORDERS.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="주문 없음")
    if order.status == "paid":
        return JSONResponse({"ok": True, "order": order.__dict__, "already": True})
    if order.status == "cancelled":
        raise HTTPException(status_code=400, detail="취소된 주문입니다.")

    payer_name = (payload.get("payer_name") or "익명").strip()[:20]
    method = payload.get("method") or "card"
    if method not in {"card", "bank", "point"}:
        method = "card"

    # 결제 처리 지연 시뮬레이션 (실제 PG처럼 잠깐 텀)
    await asyncio.sleep(0.6)

    order.status = "paid"
    order.paid_at = datetime.now().isoformat(timespec="seconds")
    order.payer_name = payer_name
    order.method = method
    HISTORY.append(order)

    await broadcast(order_id, {"type": "paid", "order": order.__dict__})
    return {"ok": True, "order": order.__dict__}


@app.post("/api/admin/reset")
async def admin_reset():
    """결제 내역 및 활성 주문을 전부 초기화 (시연용)."""
    ORDERS.clear()
    HISTORY.clear()
    SUBSCRIBERS.clear()
    return {"ok": True, "message": "모든 결제 내역이 초기화되었습니다."}


@app.post("/api/order/{order_id}/cancel")
async def cancel_order(order_id: str):
    order = ORDERS.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="주문 없음")
    if order.status == "paid":
        raise HTTPException(status_code=400, detail="이미 결제된 주문은 취소할 수 없습니다.")
    order.status = "cancelled"
    await broadcast(order_id, {"type": "cancelled", "order": order.__dict__})
    return {"ok": True}


@app.websocket("/ws/order/{order_id}")
async def ws_order(websocket: WebSocket, order_id: str):
    await websocket.accept()
    SUBSCRIBERS.setdefault(order_id, []).append(websocket)
    try:
        order = ORDERS.get(order_id)
        if order:
            await websocket.send_json({"type": "snapshot", "order": order.__dict__})
        while True:
            await websocket.receive_text()  # heartbeat / ignore
    except WebSocketDisconnect:
        pass
    finally:
        listeners = SUBSCRIBERS.get(order_id, [])
        if websocket in listeners:
            listeners.remove(websocket)


if __name__ == "__main__":
    import os
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    ip = get_lan_ip()
    print("\n" + "=" * 60)
    print(f"  QR Pay Demo 실행 중 (port={port})")
    print(f"  로컬 가맹점 화면:     http://localhost:{port}/")
    print(f"  같은 Wi-Fi 휴대폰용:  http://{ip}:{port}/")
    print(f"  관리자 (결제 내역):    http://localhost:{port}/admin")
    print("=" * 60 + "\n")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
