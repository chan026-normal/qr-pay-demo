import asyncio
import io
import json
import socket
import uuid
from base64 import b64encode
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import qrcode
from PIL import Image, ImageDraw
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

STORE_NAME = "coconut.kim"
STORE_ID = "coco-001"

# 메뉴 카탈로그 (name = 한국어 기본값, i18n = 다국어 메뉴명)
MENU = [
    {"id": "smoothie", "name": "코코넛 스무디", "price": 4500, "emoji": "🥥",
     "i18n": {"ko": "코코넛 스무디", "en": "Coconut Smoothie", "vi": "Sinh tố dừa",
              "zh": "椰子冰沙", "ja": "ココナッツスムージー"}},
    {"id": "water", "name": "코코넛 워터", "price": 2500, "emoji": "💧",
     "i18n": {"ko": "코코넛 워터", "en": "Coconut Water", "vi": "Nước dừa",
              "zh": "椰子水", "ja": "ココナッツウォーター"}},
    {"id": "chip", "name": "코코넛 칩", "price": 3000, "emoji": "🍪",
     "i18n": {"ko": "코코넛 칩", "en": "Coconut Chips", "vi": "Chip dừa",
              "zh": "椰子脆片", "ja": "ココナッツチップス"}},
]

# 다국어 (손님용 화면: 선주문 랜딩 / 주문 / 추적)
LANGS = [
    {"code": "vi", "label": "Tiếng Việt", "flag": "🇻🇳"},  # 주 무대: 최상단
    {"code": "ko", "label": "한국어", "flag": "🇰🇷"},
    {"code": "en", "label": "English", "flag": "🇺🇸"},
    {"code": "zh", "label": "中文", "flag": "🇨🇳"},
    {"code": "ja", "label": "日本語", "flag": "🇯🇵"},
]

I18N = {
    "ko": {
        "brand_sub": "선주문", "pickup_store": "매장 픽업",
        "order_title": "미리 주문하고 픽업하세요",
        "pay_method": "결제 수단", "m_card": "카드", "m_bank": "계좌이체", "m_point": "포인트",
        "name_label": "이름 (선택)", "name_ph": "홍길동",
        "btn_empty": "메뉴를 담아주세요", "btn_order": "%s 주문하기",
        "btn_processing": "결제 처리 중", "btn_retry": "다시 시도",
        "mock_note": "시연용 모의 결제 · 실제 금액 청구 없음", "install": "📲 앱 설치",
        "pickup_number": "픽업 번호", "paid_done": "결제 완료",
        "st_received_big": "접수되었습니다", "st_received_sub": "매장에서 주문을 확인하고 있어요",
        "st_preparing_big": "준비 중입니다 👨‍🍳", "st_preparing_sub": "맛있게 만들고 있어요. 조금만 기다려주세요",
        "st_ready_big": "픽업하세요! 🎉", "st_ready_sub": "준비가 완료되었습니다. 카운터에서 받아가세요",
        "st_pickedup_big": "수령 완료 ✅", "st_pickedup_sub": "이용해 주셔서 감사합니다",
        "step1": "접수", "step2": "준비중", "step3": "준비완료", "step4": "수령",
        "order_items": "주문 내역", "total": "합계", "order_no": "주문번호",
        "start_welcome": "코코넛 음료 선주문", "start_title": "앱으로 더 편하게",
        "start_sub": "홈 화면에 추가하면 다음부터 한 번에 주문하고 픽업 알림을 받아요",
        "start_install": "앱 설치하기", "start_skip": "그냥 주문하기 →",
        "ios_guide": "홈 화면에 추가하기\n\n1) 하단 공유 버튼 (□↑) 을 누르세요\n2) \"홈 화면에 추가\" 를 선택하세요\n3) \"추가\" 를 누르면 앱 아이콘이 생깁니다",
        "android_guide": "브라우저 메뉴 (⋮) 에서 \"홈 화면에 추가\" 또는 \"앱 설치\" 를 선택하세요.",
        "inapp_guide": "카카오톡·인스타 등 앱 내부 브라우저에서는 설치가 안 돼요.\n\n우측 상단 메뉴 (⋮ 또는 ···) → \"다른 브라우저로 열기\" → Chrome 으로 연 뒤 다시 시도해주세요.",
    },
    "en": {
        "brand_sub": "Pre-order", "pickup_store": "Store Pickup",
        "order_title": "Order ahead & pick up",
        "pay_method": "Payment", "m_card": "Card", "m_bank": "Transfer", "m_point": "Points",
        "name_label": "Name (optional)", "name_ph": "Your name",
        "btn_empty": "Add items to order", "btn_order": "Order %s",
        "btn_processing": "Processing…", "btn_retry": "Try again",
        "mock_note": "Demo payment · no real charge", "install": "📲 Install app",
        "pickup_number": "Pickup number", "paid_done": "Paid",
        "st_received_big": "Order received", "st_received_sub": "The store is confirming your order",
        "st_preparing_big": "Preparing 👨‍🍳", "st_preparing_sub": "We're making it. Please wait a moment",
        "st_ready_big": "Ready for pickup! 🎉", "st_ready_sub": "Your order is ready. Please collect at the counter",
        "st_pickedup_big": "Picked up ✅", "st_pickedup_sub": "Thank you for your visit",
        "step1": "Received", "step2": "Preparing", "step3": "Ready", "step4": "Pickup",
        "order_items": "Order", "total": "Total", "order_no": "Order no.",
        "start_welcome": "Coconut drinks · pre-order", "start_title": "Easier with the app",
        "start_sub": "Add to your home screen to reorder in one tap and get pickup alerts",
        "start_install": "Install app", "start_skip": "Just order →",
        "ios_guide": "Add to Home Screen\n\n1) Tap the Share button (□↑) at the bottom\n2) Choose \"Add to Home Screen\"\n3) Tap \"Add\" to create the app icon",
        "android_guide": "Open the browser menu (⋮) and choose \"Install app\" or \"Add to Home screen\".",
        "inapp_guide": "Install isn't supported in in-app browsers (KakaoTalk, Instagram, etc.).\n\nTap the menu (⋮ or ···) → \"Open in browser\" → Chrome, then try again.",
    },
    "vi": {
        "brand_sub": "Đặt trước", "pickup_store": "Nhận tại quầy",
        "order_title": "Đặt trước và đến lấy",
        "pay_method": "Thanh toán", "m_card": "Thẻ", "m_bank": "Chuyển khoản", "m_point": "Điểm",
        "name_label": "Tên (tùy chọn)", "name_ph": "Tên của bạn",
        "btn_empty": "Hãy chọn món", "btn_order": "Đặt hàng %s",
        "btn_processing": "Đang xử lý…", "btn_retry": "Thử lại",
        "mock_note": "Thanh toán thử nghiệm · không tính phí", "install": "📲 Cài app",
        "pickup_number": "Số nhận món", "paid_done": "Đã thanh toán",
        "st_received_big": "Đã nhận đơn", "st_received_sub": "Cửa hàng đang xác nhận đơn của bạn",
        "st_preparing_big": "Đang chuẩn bị 👨‍🍳", "st_preparing_sub": "Đang làm món của bạn. Vui lòng đợi một chút",
        "st_ready_big": "Sẵn sàng nhận món! 🎉", "st_ready_sub": "Đơn đã sẵn sàng. Vui lòng nhận tại quầy",
        "st_pickedup_big": "Đã nhận ✅", "st_pickedup_sub": "Cảm ơn quý khách",
        "step1": "Đã nhận", "step2": "Chuẩn bị", "step3": "Sẵn sàng", "step4": "Nhận",
        "order_items": "Đơn hàng", "total": "Tổng", "order_no": "Mã đơn",
        "start_welcome": "Đồ uống dừa · đặt trước", "start_title": "Tiện hơn với ứng dụng",
        "start_sub": "Thêm vào màn hình chính để đặt nhanh và nhận thông báo nhận món",
        "start_install": "Cài đặt ứng dụng", "start_skip": "Đặt món luôn →",
        "ios_guide": "Thêm vào Màn hình chính\n\n1) Nhấn nút Chia sẻ (□↑) ở dưới\n2) Chọn \"Thêm vào MH chính\"\n3) Nhấn \"Thêm\" để tạo biểu tượng",
        "android_guide": "Mở menu trình duyệt (⋮) và chọn \"Cài ứng dụng\" hoặc \"Thêm vào MH chính\".",
        "inapp_guide": "Không thể cài trong trình duyệt trong ứng dụng (KakaoTalk, Instagram...).\n\nNhấn menu (⋮ hoặc ···) → \"Mở bằng trình duyệt\" → Chrome, rồi thử lại.",
    },
    "zh": {
        "brand_sub": "预点单", "pickup_store": "到店取餐",
        "order_title": "提前下单，到店自取",
        "pay_method": "支付方式", "m_card": "银行卡", "m_bank": "转账", "m_point": "积分",
        "name_label": "姓名（选填）", "name_ph": "您的姓名",
        "btn_empty": "请选择商品", "btn_order": "下单 %s",
        "btn_processing": "处理中…", "btn_retry": "重试",
        "mock_note": "演示支付 · 不收取费用", "install": "📲 安装应用",
        "pickup_number": "取餐号", "paid_done": "已支付",
        "st_received_big": "已接单", "st_received_sub": "门店正在确认您的订单",
        "st_preparing_big": "制作中 👨‍🍳", "st_preparing_sub": "正在为您制作，请稍候",
        "st_ready_big": "可以取餐啦！🎉", "st_ready_sub": "您的订单已就绪，请到柜台领取",
        "st_pickedup_big": "已取餐 ✅", "st_pickedup_sub": "感谢您的惠顾",
        "step1": "接单", "step2": "制作", "step3": "就绪", "step4": "取餐",
        "order_items": "订单明细", "total": "合计", "order_no": "订单号",
        "start_welcome": "椰子饮品 · 预点单", "start_title": "用应用更方便",
        "start_sub": "添加到主屏幕，下次一键下单并接收取餐通知",
        "start_install": "安装应用", "start_skip": "直接下单 →",
        "ios_guide": "添加到主屏幕\n\n1) 点击底部分享按钮 (□↑)\n2) 选择\"添加到主屏幕\"\n3) 点击\"添加\"即可生成应用图标",
        "android_guide": "打开浏览器菜单 (⋮)，选择\"安装应用\"或\"添加到主屏幕\"。",
        "inapp_guide": "应用内置浏览器（KakaoTalk、Instagram 等）无法安装。\n\n点击右上角菜单 (⋮ 或 ···) →\"用浏览器打开\"→ Chrome，然后重试。",
    },
    "ja": {
        "brand_sub": "事前注文", "pickup_store": "店頭受取",
        "order_title": "事前に注文して受け取り",
        "pay_method": "支払い方法", "m_card": "カード", "m_bank": "振込", "m_point": "ポイント",
        "name_label": "お名前（任意）", "name_ph": "お名前",
        "btn_empty": "メニューを選んでください", "btn_order": "%s を注文",
        "btn_processing": "処理中…", "btn_retry": "再試行",
        "mock_note": "デモ決済 · 実際の請求なし", "install": "📲 アプリ",
        "pickup_number": "受取番号", "paid_done": "支払い完了",
        "st_received_big": "注文を受け付けました", "st_received_sub": "店舗が注文を確認しています",
        "st_preparing_big": "準備中 👨‍🍳", "st_preparing_sub": "心を込めて作っています。少々お待ちください",
        "st_ready_big": "受け取れます！🎉", "st_ready_sub": "ご注文の準備ができました。カウンターでお受け取りください",
        "st_pickedup_big": "受取完了 ✅", "st_pickedup_sub": "ご利用ありがとうございました",
        "step1": "受付", "step2": "準備", "step3": "完了", "step4": "受取",
        "order_items": "注文内容", "total": "合計", "order_no": "注文番号",
        "start_welcome": "ココナッツドリンク · 事前注文", "start_title": "アプリでもっと便利に",
        "start_sub": "ホーム画面に追加すれば、次回からワンタップで注文・受取通知が届きます",
        "start_install": "アプリをインストール", "start_skip": "そのまま注文 →",
        "ios_guide": "ホーム画面に追加\n\n1) 下部の共有ボタン (□↑) をタップ\n2) 「ホーム画面に追加」を選択\n3) 「追加」をタップするとアイコンが作成されます",
        "android_guide": "ブラウザメニュー (⋮) から「アプリをインストール」または「ホーム画面に追加」を選択してください。",
        "inapp_guide": "アプリ内ブラウザ（KakaoTalk、Instagram など）ではインストールできません。\n\n右上のメニュー (⋮ または ···) →「ブラウザで開く」→ Chrome を選んで再度お試しください。",
    },
}

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


_ICON_CACHE: Dict[int, bytes] = {}


def make_icon(size: int) -> bytes:
    """coconut.kim 앱 아이콘을 코드로 생성 (코코넛 무늬). static 파일 불필요."""
    if size in _ICON_CACHE:
        return _ICON_CACHE[size]
    img = Image.new("RGB", (size, size), "#8B5A2B")
    d = ImageDraw.Draw(img)
    # 배경: 카라멜 → 코코넛 브라운 세로 그라데이션
    c0, c1 = (0xC9, 0x90, 0x68), (0x4A, 0x2C, 0x1A)
    for y in range(size):
        t = y / max(1, size - 1)
        d.line(
            [(0, y), (size, y)],
            fill=tuple(int(c0[i] + (c1[i] - c0[i]) * t) for i in range(3)),
        )
    # 코코넛 단면 (크림색 원)
    pad = size * 0.22
    d.ellipse([pad, pad, size - pad, size - pad], fill="#F4E8CC")
    # 코코넛 씨눈 3개 (삼각 배치)
    cx, cy, rr = size / 2, size / 2, size * 0.055
    for ox, oy in [(0, -size * 0.10), (-size * 0.09, size * 0.06), (size * 0.09, size * 0.06)]:
        d.ellipse([cx + ox - rr, cy + oy - rr, cx + ox + rr, cy + oy + rr], fill="#5C3D2E")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    _ICON_CACHE[size] = buf.getvalue()
    return _ICON_CACHE[size]


SERVICE_WORKER_JS = """
const CACHE = 'coconut-kim-v1';
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  // 네트워크 우선 (온라인이면 항상 최신), 실패 시 캐시 폴백
  e.respondWith(
    fetch(e.request).then(resp => {
      const copy = resp.clone();
      caches.open(CACHE).then(c => c.put(e.request, copy)).catch(() => {});
      return resp;
    }).catch(() => caches.match(e.request))
  );
});
""".strip()


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
            "langs": LANGS,
        },
    )


@app.get("/order-qr", response_class=HTMLResponse)
async def order_qr_page(request: Request):
    """매장/테이블에 비치하는 선주문 진입 QR (스캔하면 /start 랜딩 열림)."""
    base = str(request.base_url).rstrip("/")
    start_url = f"{base}/start"
    return templates.TemplateResponse(
        "order_qr.html",
        {
            "request": request,
            "store_name": STORE_NAME,
            "order_url": start_url,
            "qr": make_qr_data_url(start_url),
        },
    )


@app.get("/start", response_class=HTMLResponse)
async def start_page(request: Request):
    """QR 스캔 후 첫 화면: 앱 설치 권유 (건너뛰고 바로 주문 가능)."""
    return templates.TemplateResponse(
        "start.html",
        {"request": request, "store_name": STORE_NAME, "langs": LANGS},
    )


@app.get("/i18n.js")
async def i18n_js():
    """손님 화면 다국어 사전 (JS)."""
    js = "window.LANGS=%s;window.I18N=%s;" % (
        json.dumps(LANGS, ensure_ascii=False),
        json.dumps(I18N, ensure_ascii=False),
    )
    return Response(content=js, media_type="application/javascript; charset=utf-8")


@app.get("/manifest.json")
async def web_manifest():
    """PWA 매니페스트 — 홈 화면 추가 시 앱처럼 동작하게 함."""
    return JSONResponse(
        {
            "name": "coconut.kim",
            "short_name": "coconut.kim",
            "description": "코코넛 음료 선주문 · QR 간편결제",
            "start_url": "/order",
            "scope": "/",
            "display": "standalone",
            "orientation": "portrait",
            "background_color": "#8B5A2B",
            "theme_color": "#5C3D2E",
            "lang": "ko",
            "icons": [
                {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
                {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
            ],
        }
    )


@app.get("/icon-{size}.png")
async def app_icon(size: int):
    if size not in (192, 512):
        raise HTTPException(status_code=404, detail="아이콘 크기 없음")
    return Response(content=make_icon(size), media_type="image/png")


@app.get("/sw.js")
async def service_worker():
    return Response(
        content=SERVICE_WORKER_JS,
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
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
            "menu": MENU,
            "langs": LANGS,
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
        items.append({"id": m["id"], "name": m["name"], "qty": qty, "price": m["price"]})
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
