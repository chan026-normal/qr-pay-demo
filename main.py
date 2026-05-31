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

# 메뉴 카탈로그 (가맹점 POS 화면에 표시)
MENU = [
    {"id": "smoothie", "name": "코코넛 스무디", "price": 4500, "emoji": "🥥"},
    {"id": "water", "name": "코코넛 워터", "price": 2500, "emoji": "💧"},
    {"id": "chip", "name": "코코넛 칩", "price": 3000, "emoji": "🍪"},
]

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
    # 선주문(픽업) 전용 필드
    order_type: str = "pos"  # pos | preorder
    pickup_number: Optional[int] = None  # 픽업 대기번호 (#42)
    pickup_status: Optional[str] = None  # received | preparing | ready | picked_up
    items: List[dict] = field(default_factory=list)  # [{name, qty, price}]


# 픽업 상태 한글 라벨 & 진행 순서
PICKUP_FLOW = ["received", "preparing", "ready", "picked_up"]
PICKUP_LABEL = {
    "received": "접수",
    "preparing": "준비중",
    "ready": "준비완료",
    "picked_up": "수령완료",
}

ORDERS: Dict[str, Order] = {}
HISTORY: List[Order] = []
SUBSCRIBERS: Dict[str, List[WebSocket]] = {}
KITCHEN_SUBSCRIBERS: List[WebSocket] = []
PICKUP_COUNTER = {"n": 0}


def next_pickup_number() -> int:
    PICKUP_COUNTER["n"] += 1
    return PICKUP_COUNTER["n"]


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


async def broadcast_kitchen(event: dict) -> None:
    """주방 디스플레이 화면 전체에 이벤트 전송."""
    dead: List[WebSocket] = []
    for ws in KITCHEN_SUBSCRIBERS:
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        KITCHEN_SUBSCRIBERS.remove(ws)


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
            "menu": MENU,
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


@app.get("/order", response_class=HTMLResponse)
async def order_page(request: Request):
    """손님 셀프 선주문 화면 (메뉴 → 장바구니 → 결제 → 픽업번호)."""
    return templates.TemplateResponse(
        "order.html",
        {
            "request": request,
            "store_name": STORE_NAME,
            "menu": MENU,
        },
    )


@app.get("/order-qr", response_class=HTMLResponse)
async def order_qr_page(request: Request):
    """매장/테이블에 비치하는 선주문 진입 QR (스캔하면 /order 열림)."""
    base = str(request.base_url).rstrip("/")
    order_url = f"{base}/order"
    return templates.TemplateResponse(
        "order_qr.html",
        {
            "request": request,
            "store_name": STORE_NAME,
            "order_url": order_url,
            "qr": make_qr_data_url(order_url),
        },
    )


@app.get("/track/{order_id}", response_class=HTMLResponse)
async def track_page(request: Request, order_id: str):
    """손님 주문 추적 화면 (픽업번호 + 실시간 준비 상태)."""
    order = ORDERS.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다.")
    return templates.TemplateResponse(
        "track.html",
        {
            "request": request,
            "store_name": STORE_NAME,
            "order": order,
        },
    )


@app.get("/kitchen", response_class=HTMLResponse)
async def kitchen_page(request: Request):
    """주방/카운터 디스플레이 (들어온 선주문 상태 관리)."""
    return templates.TemplateResponse(
        "kitchen.html",
        {
            "request": request,
            "store_name": STORE_NAME,
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


@app.post("/api/preorder")
async def create_preorder(payload: dict):
    """손님이 직접 만든 선주문을 결제 처리하고 픽업번호 발급."""
    raw_items = payload.get("items") or []
    menu_by_id = {m["id"]: m for m in MENU}

    items: List[dict] = []
    amount = 0
    for it in raw_items:
        m = menu_by_id.get(it.get("id"))
        if not m:
            continue
        qty = max(0, min(int(it.get("qty", 0)), 99))
        if qty == 0:
            continue
        items.append({"name": m["name"], "qty": qty, "price": m["price"]})
        amount += m["price"] * qty

    if not items or amount <= 0:
        raise HTTPException(status_code=400, detail="주문 항목이 비어 있습니다.")

    payer_name = (payload.get("payer_name") or "손님").strip()[:20]
    method = payload.get("method") or "card"
    if method not in {"card", "bank", "point"}:
        method = "card"

    # 결제 처리 지연 시뮬레이션
    await asyncio.sleep(0.6)

    order_id = uuid.uuid4().hex[:10].upper()
    memo = ", ".join(f"{i['name']} x{i['qty']}" for i in items)
    order = Order(
        order_id=order_id,
        amount=amount,
        memo=memo,
        status="paid",
        paid_at=datetime.now().isoformat(timespec="seconds"),
        payer_name=payer_name,
        method=method,
        order_type="preorder",
        pickup_number=next_pickup_number(),
        pickup_status="received",
        items=items,
    )
    ORDERS[order_id] = order
    HISTORY.append(order)

    base = (payload.get("base") or "").rstrip("/")
    track_url = f"{base}/track/{order_id}" if base else f"/track/{order_id}"

    # 주방 디스플레이에 새 주문 알림
    await broadcast_kitchen({"type": "new_order", "order": order.__dict__})

    return {
        "ok": True,
        "order_id": order_id,
        "pickup_number": order.pickup_number,
        "amount": amount,
        "track_url": track_url,
    }


@app.post("/api/order/{order_id}/status")
async def update_pickup_status(order_id: str, payload: dict):
    """주방이 주문 상태를 다음 단계로 변경 (접수→준비중→준비완료→수령)."""
    order = ORDERS.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="주문 없음")
    if order.order_type != "preorder":
        raise HTTPException(status_code=400, detail="선주문이 아닙니다.")

    new_status = payload.get("status")
    if new_status not in PICKUP_FLOW:
        raise HTTPException(status_code=400, detail="잘못된 상태값입니다.")

    order.pickup_status = new_status
    event = {"type": "status", "order": order.__dict__}
    await broadcast(order_id, event)       # 손님 추적 화면 갱신
    await broadcast_kitchen(event)         # 다른 주방 화면 동기화
    return {"ok": True, "order": order.__dict__}


@app.get("/api/kitchen/orders")
async def kitchen_orders():
    """주방 화면 초기 로드용: 활성 선주문 목록 (픽업번호 순)."""
    active = [
        o.__dict__
        for o in ORDERS.values()
        if o.order_type == "preorder" and o.pickup_status != "picked_up"
    ]
    active.sort(key=lambda o: o.get("pickup_number") or 0)
    return {"orders": active}


@app.post("/api/admin/reset")
async def admin_reset():
    """결제 내역 및 활성 주문을 전부 초기화 (시연용)."""
    ORDERS.clear()
    HISTORY.clear()
    SUBSCRIBERS.clear()
    PICKUP_COUNTER["n"] = 0
    await broadcast_kitchen({"type": "reset"})
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


@app.websocket("/ws/kitchen")
async def ws_kitchen(websocket: WebSocket):
    """주방 디스플레이용 실시간 채널 (새 주문 / 상태 변경 수신)."""
    await websocket.accept()
    KITCHEN_SUBSCRIBERS.append(websocket)
    try:
        while True:
            await websocket.receive_text()  # heartbeat / ignore
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in KITCHEN_SUBSCRIBERS:
            KITCHEN_SUBSCRIBERS.remove(websocket)


if __name__ == "__main__":
    import os
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    ip = get_lan_ip()
    print("\n" + "=" * 64)
    print(f"  QR Pay Demo 실행 중 (port={port})")
    print(f"  가맹점 POS:          http://localhost:{port}/")
    print(f"  손님 선주문:          http://localhost:{port}/order")
    print(f"  선주문 진입 QR:       http://localhost:{port}/order-qr")
    print(f"  주방 디스플레이:       http://localhost:{port}/kitchen")
    print(f"  관리자 (결제 내역):    http://localhost:{port}/admin")
    print(f"  같은 Wi-Fi 휴대폰용:  http://{ip}:{port}/order")
    print("=" * 64 + "\n")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
