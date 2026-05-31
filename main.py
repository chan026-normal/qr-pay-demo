import asyncio
import csv
import io
import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
import uuid
from base64 import b64encode
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

# 매장 표준시 (기본 한국 KST=+9, 베트남 운영 시 TZ_OFFSET_HOURS=7 로 설정)
APP_TZ = timezone(timedelta(hours=float(os.environ.get("TZ_OFFSET_HOURS", "9"))))


def now_str() -> str:
    """매장 표준시 기준 ISO 시각 문자열 (타임존 표기 없는 로컬 시각)."""
    return datetime.now(APP_TZ).replace(tzinfo=None).isoformat(timespec="seconds")

import qrcode
from PIL import Image, ImageDraw
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

STORE_NAME = "coconut.kim"
STORE_ID = "coco-001"
# 카카오톡 채널 링크 (환경변수로 교체 가능). 오픈채팅이면 open.kakao.com/o/... 로 바꾸면 됨
KAKAO_CHANNEL_URL = os.environ.get("KAKAO_CHANNEL_URL", "https://pf.kakao.com/_PTebX")
# 결제내역 초기화 보호 암호. 설정하면 /admin 초기화에 암호를 요구, 비워두면 암호 없이 동작(하위호환).
ADMIN_PIN = os.environ.get("ADMIN_PIN", "")

# 메뉴 카탈로그 (name = 한국어 기본값, i18n = 다국어 메뉴명)
# badge: 수동 배지 ("new"=신메뉴, "reco"=추천, None=없음). "hot"(인기)은 판매량으로 자동 부여.
MENU = [
    {"id": "smoothie", "name": "코코넛 스무디", "price": 4500, "emoji": "🥥", "badge": None,
     "i18n": {"ko": "코코넛 스무디", "en": "Coconut Smoothie", "vi": "Sinh tố dừa",
              "zh": "椰子冰沙", "ja": "ココナッツスムージー"}},
    {"id": "water", "name": "코코넛 워터", "price": 2500, "emoji": "💧", "badge": None,
     "i18n": {"ko": "코코넛 워터", "en": "Coconut Water", "vi": "Nước dừa",
              "zh": "椰子水", "ja": "ココナッツウォーター"}},
    {"id": "chip", "name": "코코넛 칩", "price": 3000, "emoji": "🍪", "badge": "new",
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
        "pay_method": "결제 수단", "m_card": "카드", "m_cash": "현금",
        "m_momo": "MoMo", "m_zalopay": "ZaloPay", "m_mobilepay": "간편결제",
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
        "samsung_guide": "삼성 인터넷에서는 설치 시 안드로이드 보안 차단(\"안전하지 않은 앱\")이 뜰 수 있어요.\n\n• Chrome 으로 열면 정상 설치됩니다.\n• 또는 설치 없이 이 화면에서 바로 주문하셔도 됩니다.",
        "nl_title": "🤖 말로 주문하기", "nl_ph": "예: 워터1 스무디2", "nl_btn": "담기",
        "nl_thinking": "분석 중…", "nl_none": "맞는 메뉴를 찾지 못했어요", "upsell_title": "함께 즐기면 좋아요",
        "menu_label": "메뉴", "clear_cart": "전체 비우기",
        "reset_order": "🔄 주문 초기화", "nl_reset_done": "주문을 초기화했어요",
        "badge_hot": "🔥 인기", "badge_new": "✨ 신메뉴", "badge_reco": "👍 추천",
        "stamp_title": "스탬프 적립", "stamp_free": "🎁 무료 음료 쿠폰 획득!",
        "stamp_progress": "%s잔 더 모으면 무료 음료 🎁", "stamp_earned": "이번 적립 +%s개",
        "share_btn": "📣 공유하기", "share_text": "coconut.kim 🥥 폰으로 미리 주문하고 준비되면 픽업! 스탬프 모으면 무료 음료 🎁 지금 주문 👉",
        "share_copied": "공유 링크를 복사했어요!", "kakao_btn": "💬 카카오톡 채널",
        "share_cta": "오늘의 코코넛 한 잔, 자랑해볼까요? 🥥✨",
    },
    "en": {
        "brand_sub": "Pre-order", "pickup_store": "Store Pickup",
        "order_title": "Order ahead & pick up",
        "pay_method": "Payment", "m_card": "Card", "m_cash": "Cash",
        "m_momo": "MoMo", "m_zalopay": "ZaloPay", "m_mobilepay": "Mobile Pay",
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
        "samsung_guide": "On Samsung Internet, Android may block the install (\"unsafe app\").\n\n• Open in Chrome to install properly.\n• Or just order here without installing.",
        "nl_title": "🤖 Order by text", "nl_ph": "e.g. 2 cold coconut drinks", "nl_btn": "Add",
        "nl_thinking": "Thinking…", "nl_none": "No matching items found", "upsell_title": "Goes well with",
        "menu_label": "Menu", "clear_cart": "Clear all",
        "reset_order": "🔄 Reset order", "nl_reset_done": "Order cleared",
        "badge_hot": "🔥 Popular", "badge_new": "✨ New", "badge_reco": "👍 Pick",
        "stamp_title": "Stamps", "stamp_free": "🎁 Free drink coupon earned!",
        "stamp_progress": "%s more for a free drink 🎁", "stamp_earned": "+%s earned",
        "share_btn": "📣 Share", "share_text": "coconut.kim 🥥 Order ahead on your phone, pick up when ready! Collect stamps for a free drink 🎁 Order now 👉",
        "share_copied": "Link copied!", "kakao_btn": "💬 KakaoTalk Channel",
        "share_cta": "Show off your coconut moment 🥥✨",
    },
    "vi": {
        "brand_sub": "Đặt trước", "pickup_store": "Nhận tại quầy",
        "order_title": "Đặt trước và đến lấy",
        "pay_method": "Thanh toán", "m_card": "Thẻ", "m_cash": "Tiền mặt",
        "m_momo": "MoMo", "m_zalopay": "ZaloPay", "m_mobilepay": "Ví điện tử",
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
        "samsung_guide": "Trên Samsung Internet, Android có thể chặn cài đặt (\"ứng dụng không an toàn\").\n\n• Mở bằng Chrome để cài đúng cách.\n• Hoặc đặt món ngay tại đây mà không cần cài.",
        "nl_title": "🤖 Đặt bằng lời", "nl_ph": "vd: 2 ly nước dừa mát", "nl_btn": "Thêm",
        "nl_thinking": "Đang xử lý…", "nl_none": "Không tìm thấy món phù hợp", "upsell_title": "Dùng kèm ngon hơn",
        "menu_label": "Thực đơn", "clear_cart": "Xóa hết",
        "reset_order": "🔄 Đặt lại đơn", "nl_reset_done": "Đã xóa đơn hàng",
        "badge_hot": "🔥 Phổ biến", "badge_new": "✨ Mới", "badge_reco": "👍 Đề xuất",
        "stamp_title": "Tem tích lũy", "stamp_free": "🎁 Nhận phiếu đồ uống miễn phí!",
        "stamp_progress": "Thêm %s ly để được tặng đồ uống 🎁", "stamp_earned": "+%s tem",
        "share_btn": "📣 Chia sẻ", "share_text": "coconut.kim 🥥 Đặt trước bằng điện thoại, lấy khi sẵn sàng! Tích tem đổi đồ uống miễn phí 🎁 Đặt ngay 👉",
        "share_copied": "Đã sao chép liên kết!", "kakao_btn": "💬 Kênh KakaoTalk",
        "share_cta": "Khoe ly dừa của bạn nào 🥥✨",
    },
    "zh": {
        "brand_sub": "预点单", "pickup_store": "到店取餐",
        "order_title": "提前下单，到店自取",
        "pay_method": "支付方式", "m_card": "银行卡", "m_cash": "现金",
        "m_momo": "MoMo", "m_zalopay": "ZaloPay", "m_mobilepay": "手机支付",
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
        "samsung_guide": "在三星浏览器中，安装可能被 Android 拦截（\"不安全的应用\"）。\n\n• 用 Chrome 打开即可正常安装。\n• 或无需安装，直接在此页面下单。",
        "nl_title": "🤖 用语言点单", "nl_ph": "如：2杯冰椰子饮品", "nl_btn": "添加",
        "nl_thinking": "分析中…", "nl_none": "未找到匹配商品", "upsell_title": "搭配更美味",
        "menu_label": "菜单", "clear_cart": "全部清空",
        "reset_order": "🔄 重新下单", "nl_reset_done": "已清空订单",
        "badge_hot": "🔥 热门", "badge_new": "✨ 新品", "badge_reco": "👍 推荐",
        "stamp_title": "集点", "stamp_free": "🎁 获得免费饮品券！",
        "stamp_progress": "再集 %s 杯即可免费 🎁", "stamp_earned": "本次 +%s",
        "share_btn": "📣 分享", "share_text": "coconut.kim 🥥 手机提前点单，做好就取！集点换免费饮品 🎁 立即点单 👉",
        "share_copied": "已复制链接！", "kakao_btn": "💬 KakaoTalk 频道",
        "share_cta": "晒一晒你的椰子时刻 🥥✨",
    },
    "ja": {
        "brand_sub": "事前注文", "pickup_store": "店頭受取",
        "order_title": "事前に注文して受け取り",
        "pay_method": "支払い方法", "m_card": "カード", "m_cash": "現金",
        "m_momo": "MoMo", "m_zalopay": "ZaloPay", "m_mobilepay": "モバイル決済",
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
        "samsung_guide": "Samsung Internet ではインストール時に Android のセキュリティでブロック（「安全でないアプリ」）されることがあります。\n\n• Chrome で開くと正常にインストールできます。\n• またはインストールせず、この画面でそのまま注文できます。",
        "nl_title": "🤖 言葉で注文", "nl_ph": "例: 冷たいココナッツ2つ", "nl_btn": "追加",
        "nl_thinking": "処理中…", "nl_none": "該当メニューが見つかりません", "upsell_title": "一緒にいかが",
        "menu_label": "メニュー", "clear_cart": "全て削除",
        "reset_order": "🔄 注文リセット", "nl_reset_done": "注文をリセットしました",
        "badge_hot": "🔥 人気", "badge_new": "✨ 新商品", "badge_reco": "👍 おすすめ",
        "stamp_title": "スタンプ", "stamp_free": "🎁 無料ドリンク券を獲得！",
        "stamp_progress": "あと %s 杯で無料ドリンク 🎁", "stamp_earned": "今回 +%s",
        "share_btn": "📣 シェア", "share_text": "coconut.kim 🥥 スマホで事前注文、できたら受取！スタンプで無料ドリンク 🎁 今すぐ注文 👉",
        "share_copied": "リンクをコピーしました！", "kakao_btn": "💬 カカオチャンネル",
        "share_cta": "今日のココナッツ、自慢しちゃおう 🥥✨",
    },
}

# 언어 → 통화 매핑 (가격 자동 변환용). 기준 통화는 원화(KRW).
CURRENCY_BY_LANG = {
    "ko": {"code": "KRW", "locale": "ko-KR"},
    "vi": {"code": "VND", "locale": "vi-VN"},
    "en": {"code": "USD", "locale": "en-US"},
    "zh": {"code": "CNY", "locale": "zh-CN"},
    "ja": {"code": "JPY", "locale": "ja-JP"},
}

# 결제수단 카탈로그 (key = 저장·통계용 식별자, color = admin 차트색).
# 라벨은 I18N의 "m_<key>" 키로 다국어 처리. 고유명사(MoMo/ZaloPay)는 전 언어 동일.
PAYMENT_METHODS = {
    "momo":      {"color": "#A50064"},  # 베트남 1위 전자지갑
    "zalopay":   {"color": "#0068FF"},  # Zalo 메신저 내장 결제
    "cash":      {"color": "#16A34A"},  # 현금
    "card":      {"color": "#B45309"},  # 해외 신용/체크카드 (Visa·Master)
    "mobilepay": {"color": "#1F2937"},  # Apple/Google Pay 등 간편결제
}
# 언어별 노출 결제수단 — 타깃 고객층에 맞춤.
#   vi(현지 Gen Z): 현지에서 일상적으로 쓰는 MoMo·ZaloPay·현금
#   외국어(관광객): 베트남 e-wallet은 현지 은행계좌가 있어야 충전돼 사실상 못 씀.
#                   → 실제로 쓰는 해외카드·현금·간편결제(Apple/Google Pay)로 노출.
PAYMENT_BY_LANG = {
    "vi": ["momo", "zalopay", "cash"],
    "ko": ["card", "cash", "mobilepay"],
    "en": ["card", "cash", "mobilepay"],
    "zh": ["card", "cash", "mobilepay"],
    "ja": ["card", "cash", "mobilepay"],
}
DEFAULT_METHODS = ["card", "cash", "mobilepay"]  # 미정의 언어 폴백

TARGET_CODES = ["KRW", "USD", "VND", "CNY", "JPY"]
# 폴백 환율 (1 KRW 당) — 실시간 API 실패 시 사용 (대략값, 데모 안전망)
FALLBACK_RATES = {"KRW": 1.0, "USD": 0.00072, "VND": 18.3, "CNY": 0.0052, "JPY": 0.11}
RATE_TTL = 6 * 3600  # 6시간마다 갱신 (무료 API는 하루 1회 갱신)
_RATE_CACHE = {"rates": None, "ts": 0.0, "live": False}


def _fetch_rates_sync() -> dict:
    url = "https://open.er-api.com/v6/latest/KRW"
    with urllib.request.urlopen(url, timeout=5) as r:
        data = json.loads(r.read())
    rates = data.get("rates", {})
    return {c: rates[c] for c in TARGET_CODES if c in rates}


async def get_rates() -> dict:
    now = time.time()
    if _RATE_CACHE["rates"] and now - _RATE_CACHE["ts"] < RATE_TTL:
        return _RATE_CACHE
    try:
        rates = await asyncio.to_thread(_fetch_rates_sync)
        if rates.get("VND") and rates.get("USD"):  # 정상 응답 확인
            rates["KRW"] = 1.0
            _RATE_CACHE.update(rates=rates, ts=now, live=True)
            return _RATE_CACHE
    except Exception:
        pass
    if not _RATE_CACHE["rates"]:  # API 실패 & 캐시 없음 → 폴백
        _RATE_CACHE.update(rates=dict(FALLBACK_RATES), ts=now, live=False)
    return _RATE_CACHE


# ── AI (OpenAI / ChatGPT) ─────────────────────────────────────────────
# OPENAI_API_KEY 환경변수가 있으면 실제 ChatGPT 사용, 없으면 통계/키워드 폴백.
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


def _openai_chat_sync(system: str, user: str) -> str:
    body = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read())
    return data["choices"][0]["message"]["content"]


async def llm_json(system: str, user: str):
    """OpenAI에 JSON 응답 요청. 키 없거나 실패 시 None."""
    if not OPENAI_API_KEY:
        return None
    try:
        text = await asyncio.to_thread(_openai_chat_sync, system, user)
        return json.loads(text)
    except Exception:
        return None


def _resolve_items(raw) -> List[dict]:
    """LLM/입력이 준 [{id, qty}]를 메뉴와 대조해 검증."""
    by_id = {m["id"]: m for m in MENU}
    out = []
    for it in raw or []:
        m = by_id.get(it.get("id"))
        if not m:
            continue
        try:
            qty = int(it.get("qty", 1))
        except (TypeError, ValueError):
            qty = 1
        out.append({"id": m["id"], "qty": max(1, min(qty, 99)), "name": m["name"]})
    return out


_NUM_WORDS = {
    "하나": 1, "한": 1, "둘": 2, "두": 2, "셋": 3, "세": 3, "넷": 4, "네": 4, "다섯": 5,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
}
# 메뉴별 추가 키워드 (짧은 표현·축약형 매칭용)
_EXTRA_KW = {
    "smoothie": ["스무디", "smoothie", "sinh tố", "sinh to", "冰沙", "スムージー"],
    "water": ["워터", "water", "nước dừa", "nuoc dua", "椰子水", "ウォーター"],
    "chip": ["칩", "chip", "脆片", "チップ"],
}


def _qty_from(s: str):
    nums = re.findall(r"\d+", s)
    if nums:
        return int(nums[0])
    for w, n in _NUM_WORDS.items():
        if w in s:
            return n
    return None


def _keyword_match(text: str) -> List[dict]:
    """폴백: 메뉴명(다국어)+키워드를 텍스트에서 찾아 수량과 함께 추출."""
    t = text.lower()
    out = []
    for m in MENU:
        keywords = [m["name"].lower()] + [v.lower() for v in m["i18n"].values()] + _EXTRA_KW.get(m["id"], [])
        pos, matched = -1, ""
        for kw in keywords:
            p = t.find(kw.lower())
            if p >= 0:
                pos, matched = p, kw
                break
        if pos < 0:
            continue
        end = pos + len(matched)
        # 수량: 한국어는 명사 뒤("칩 2개"), 영어는 앞("2 chips") → 뒤 먼저, 그다음 앞
        qty = _qty_from(t[end:end + 5]) or _qty_from(t[max(0, pos - 5):pos]) or 1
        out.append({"id": m["id"], "qty": max(1, min(qty, 99)), "name": m["name"]})
    return out


app = FastAPI(title="QR Pay Demo")
templates = Jinja2Templates(directory="templates")


@dataclass
class Order:
    order_id: str
    amount: int
    memo: str
    status: str = "pending"  # pending | paid | cancelled
    created_at: str = field(default_factory=now_str)
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

# 스탬프 적립 (시연용): 주문 1건당 +1, 추가로 결제금액 1만원당 +1, 10개=무료 음료
STAMP_GOAL = 10
STAMP_PER_AMOUNT = 10000
STAMPS = {"count": 0}


def earn_stamps(amount: int) -> int:
    """이번 결제로 적립되는 스탬프 수 = 1(주문) + 금액//1만원."""
    earned = 1 + (max(0, amount) // STAMP_PER_AMOUNT)
    STAMPS["count"] += earned
    return earned


def stamp_state() -> dict:
    c = STAMPS["count"]
    filled = c % STAMP_GOAL
    free = c > 0 and filled == 0
    if free:
        filled = STAMP_GOAL
    return {"count": c, "goal": STAMP_GOAL, "filled": filled, "free": free}


def hot_item_ids() -> List[str]:
    """자동 '인기' 배지 = 판매량 1위. 단, 직원이 '인기'를 수동 지정했으면 자동은 끔."""
    if any(m.get("badge") == "hot" for m in MENU):
        return []
    pop: Dict[str, int] = {}
    for o in HISTORY:
        for it in o.items:
            pop[it["id"]] = pop.get(it["id"], 0) + it["qty"]
    if not pop:
        return []
    top = max(pop.values())
    return [k for k, v in pop.items() if v == top and v > 0][:1]


# ── 데이터베이스 (선택) ──────────────────────────────────────────────
# DATABASE_URL 환경변수가 있으면 주문·배지를 영구 저장. 없으면 메모리만 사용(기존 동작).
DATABASE_URL = os.environ.get("DATABASE_URL", "")
_engine = None
if DATABASE_URL:
    try:
        from sqlalchemy import create_engine, text as _sql
        _url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        _engine = create_engine(_url, pool_pre_ping=True)
        with _engine.begin() as _c:
            _c.execute(_sql("CREATE TABLE IF NOT EXISTS orders (order_id TEXT PRIMARY KEY, json TEXT NOT NULL, paid_at TEXT)"))
            _c.execute(_sql("CREATE TABLE IF NOT EXISTS menu_badges (item_id TEXT PRIMARY KEY, badge TEXT)"))
        print("[DB] connected — 영구 저장 활성화")
    except Exception as e:
        _engine = None
        print(f"[DB] 연결 실패 → 메모리 모드로 동작: {e}")

DB_ENABLED = _engine is not None


def db_save_order(order: "Order") -> None:
    if not DB_ENABLED:
        return
    try:
        from sqlalchemy import text as _sql
        with _engine.begin() as c:
            c.execute(
                _sql("INSERT INTO orders (order_id, json, paid_at) VALUES (:oid, :j, :p) "
                     "ON CONFLICT (order_id) DO UPDATE SET json = :j, paid_at = :p"),
                {"oid": order.order_id, "j": json.dumps(order.__dict__, ensure_ascii=False), "p": order.paid_at},
            )
    except Exception as e:
        print(f"[DB] save_order error: {e}")


def db_save_badge(item_id: str, badge) -> None:
    if not DB_ENABLED:
        return
    try:
        from sqlalchemy import text as _sql
        with _engine.begin() as c:
            c.execute(
                _sql("INSERT INTO menu_badges (item_id, badge) VALUES (:i, :b) "
                     "ON CONFLICT (item_id) DO UPDATE SET badge = :b"),
                {"i": item_id, "b": badge},
            )
    except Exception as e:
        print(f"[DB] save_badge error: {e}")


def db_clear_orders() -> None:
    if not DB_ENABLED:
        return
    try:
        from sqlalchemy import text as _sql
        with _engine.begin() as c:
            c.execute(_sql("DELETE FROM orders"))
    except Exception as e:
        print(f"[DB] clear error: {e}")


def db_load() -> None:
    """서버 시작 시 DB에서 주문·배지를 메모리로 복원."""
    if not DB_ENABLED:
        return
    try:
        from sqlalchemy import text as _sql
        fields = set(Order.__dataclass_fields__)
        with _engine.begin() as c:
            rows = c.execute(_sql("SELECT json FROM orders ORDER BY paid_at")).fetchall()
            for (j,) in rows:
                d = json.loads(j)
                o = Order(**{k: v for k, v in d.items() if k in fields})
                ORDERS[o.order_id] = o
                if o.status == "paid":
                    HISTORY.append(o)
                if o.pickup_number:
                    PICKUP_COUNTER["n"] = max(PICKUP_COUNTER["n"], o.pickup_number)
            STAMPS["count"] = sum(1 + (o.amount // STAMP_PER_AMOUNT) for o in HISTORY)
            bmap = dict(c.execute(_sql("SELECT item_id, badge FROM menu_badges")).fetchall())
            for m in MENU:
                if m["id"] in bmap:
                    m["badge"] = bmap[m["id"]]
        print(f"[DB] 복원 완료 — 주문 {len(HISTORY)}건, 스탬프 {STAMPS['count']}개")
    except Exception as e:
        print(f"[DB] load error: {e}")


@app.on_event("startup")
async def _on_startup():
    db_load()


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


def make_qr_png_bytes(url: str, box_size: int = 10) -> bytes:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0F172A", back_color="#FFFFFF")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_qr_data_url(url: str) -> str:
    return "data:image/png;base64," + b64encode(make_qr_png_bytes(url)).decode()


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


@app.get("/health")
@app.head("/health")
async def health():
    """UptimeRobot 등 모니터링용 가벼운 헬스체크 (서버 깨우기)."""
    return {"status": "ok"}


@app.head("/")
async def merchant_head():
    """UptimeRobot이 HEAD로 핑해도 200을 반환 (콜드 스타트 깨우기용)."""
    return Response(status_code=200)


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


def _item_stats():
    """결제 완료된 주문에서 품목별 판매량·매출 집계."""
    stats: Dict[str, dict] = {}
    for o in HISTORY:
        for it in o.items:
            s = stats.setdefault(it["id"], {"name": it["name"], "qty": 0, "revenue": 0})
            s["qty"] += it["qty"]
            s["revenue"] += it["qty"] * it["price"]
    return sorted(stats.values(), key=lambda x: -x["qty"])


def _hourly_stats():
    """시간대(0~23시)별 매출 집계."""
    hourly: Dict[int, int] = {}
    for o in HISTORY:
        if o.paid_at and len(o.paid_at) >= 13:
            try:
                h = int(o.paid_at[11:13])
            except ValueError:
                continue
            hourly[h] = hourly.get(h, 0) + o.amount
    return [{"hour": h, "revenue": hourly[h]} for h in sorted(hourly)]


def _method_stats():
    """결제수단별 건수·매출·비율 집계."""
    labels = {"momo": "MoMo", "zalopay": "ZaloPay", "cash": "현금", "card": "카드",
              "mobilepay": "간편결제", "bank": "계좌이체", "point": "포인트", "etc": "기타"}
    colors = {k: v["color"] for k, v in PAYMENT_METHODS.items()}
    colors.update({"bank": "#2563EB", "point": "#059669", "etc": "#78716C"})
    ms: Dict[str, dict] = {}
    total = 0
    for o in HISTORY:
        m = o.method or "etc"
        s = ms.setdefault(m, {"method": m, "count": 0, "revenue": 0})
        s["count"] += 1
        s["revenue"] += o.amount
        total += o.amount
    out = []
    for m, s in ms.items():
        s["label"] = labels.get(m, m)
        s["color"] = colors.get(m, "#78716C")
        s["pct"] = round(s["revenue"] / total * 100, 1) if total else 0
        out.append(s)
    return sorted(out, key=lambda x: -x["revenue"])


def _smart_insights():
    """매출 데이터 기반 운영 인사이트 생성 (통계/규칙 기반 — 추후 LLM으로 교체 가능).

    반환: 현황 분석 / 수요 예측·발주 / 함께 팔리는 조합 / 실행 추천
    """
    from itertools import combinations

    if not HISTORY:
        return {
            "insights": ["아직 분석할 주문 데이터가 없습니다. 주문이 쌓이면 자동으로 분석합니다."],
            "forecast": [], "combos": [], "recommendations": [],
        }

    total_rev = sum(o.amount for o in HISTORY)
    n_orders = len(HISTORY)
    item_stats = _item_stats()
    method_stats = _method_stats()
    hourly = _hourly_stats()
    name_by_id = {m["id"]: m["name"] for m in MENU}

    insights, forecast, combos, recommendations = [], [], [], []

    # ① 현황 분석 (간결 헤드라인 스타일)
    avg = total_rev // n_orders if n_orders else 0
    insights.append(f"총 {n_orders}건 · 매출 {total_rev:,}원 · 객단가 {avg:,}원")
    if item_stats:
        top = item_stats[0]
        share = round(top["revenue"] / total_rev * 100) if total_rev else 0
        insights.append(f"인기 메뉴 {top['name']} — {top['qty']}개 · 매출 {share}%")
    if method_stats:
        insights.append(f"결제 {method_stats[0]['label']} 비중 {method_stats[0]['pct']}%")

    # ⑤ 수요 예측 · 발주
    if hourly:
        peak = max(hourly, key=lambda h: h["revenue"])
        forecast.append(f"매출 피크 {peak['hour']}시대 — 인력·재고 보강")
    if item_stats:
        forecast.append(f"{item_stats[0]['name']} 회전 빠름 → 재고 넉넉히")
        if len(item_stats) > 1:
            slow = item_stats[-1]
            forecast.append(f"{slow['name']} 판매 더딤 → 세트·프로모션 검토")

    # ④ 함께 팔리는 조합 (동시 주문 빈도)
    pair_count: Dict[tuple, int] = {}
    for o in HISTORY:
        ids = sorted({it["id"] for it in o.items})
        for a, b in combinations(ids, 2):
            pair_count[(a, b)] = pair_count.get((a, b), 0) + 1
    for (a, b), c in sorted(pair_count.items(), key=lambda x: -x[1])[:3]:
        combos.append(f"{name_by_id.get(a, a)} + {name_by_id.get(b, b)} 함께 {c}회 — 세트로 객단가 ↑")
    if not combos:
        combos.append("함께 주문 데이터 부족 — 주문 쌓이면 세트 추천")

    # 💡 실행 추천
    cash = next((m for m in method_stats if m["method"] == "cash"), None)
    if cash and cash["pct"] >= 50:
        recommendations.append("현금 결제 비중 높음 → MoMo·ZaloPay 간편결제 유도로 회전율↑·정산 간소화")
    if item_stats and total_rev and round(item_stats[0]["revenue"] / total_rev * 100) > 55:
        recommendations.append(f"{item_stats[0]['name']} 의존도 높음 → 다른 메뉴 프로모션으로 분산")
    recommendations.append("외국어 주문 비중 관찰 → 인기 언어권 현지화 마케팅")

    return {"insights": insights, "forecast": forecast, "combos": combos, "recommendations": recommendations}


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    stats = _item_stats()
    max_qty = max((s["qty"] for s in stats), default=0)
    hourly = _hourly_stats()
    max_hour_rev = max((h["revenue"] for h in hourly), default=0)
    methods = _method_stats()
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "store_name": STORE_NAME,
            "orders": list(reversed(HISTORY))[:50],
            "item_stats": stats,
            "max_qty": max_qty,
            "hourly_stats": hourly,
            "max_hour_rev": max_hour_rev,
            "method_stats": methods,
            "menu": MENU,
            "pin_required": bool(ADMIN_PIN),
        },
    )


@app.post("/api/admin/badge")
async def set_badge(payload: dict):
    """직원이 메뉴 배지를 수동 지정 (없음 / 인기 / 신메뉴 / 추천). 인기 미지정 시 판매량 1위 자동."""
    item_id = payload.get("id")
    badge = payload.get("badge") or None
    if badge not in (None, "hot", "new", "reco"):
        raise HTTPException(status_code=400, detail="잘못된 배지값입니다.")
    for m in MENU:
        if m["id"] == item_id:
            m["badge"] = badge
            db_save_badge(item_id, badge)
            return {"ok": True, "id": item_id, "badge": badge}
    raise HTTPException(status_code=404, detail="메뉴를 찾을 수 없습니다.")


@app.get("/api/insights")
async def api_insights():
    """스마트 운영 리포트. OPENAI_API_KEY 있으면 ChatGPT 분석, 없으면 통계 기반."""
    base = _smart_insights()
    if not OPENAI_API_KEY or not HISTORY:
        base["ai"] = False
        return base

    item_stats = _item_stats()  # 수량 내림차순 정렬
    method_stats = _method_stats()
    hourly = _hourly_stats()
    peak = max(hourly, key=lambda h: h["revenue"]) if hourly else None

    # 순위 계산은 Python이 미리 확정 → LLM이 최대/최소를 틀리지 않게 못박음
    facts = {
        "top_seller": item_stats[0]["name"] if item_stats else None,
        "top_seller_qty": item_stats[0]["qty"] if item_stats else 0,
        "lowest_seller": item_stats[-1]["name"] if item_stats else None,
        "lowest_seller_qty": item_stats[-1]["qty"] if item_stats else 0,
        "peak_hour": peak["hour"] if peak else None,
        "dominant_method": method_stats[0]["label"] if method_stats else None,
    }
    context = {
        "FACTS_GROUND_TRUTH": facts,
        "item_stats_sorted_by_qty_desc": item_stats,
        "method_stats": [
            {"label": m["label"], "count": m["count"], "revenue": m["revenue"], "pct": m["pct"]}
            for m in method_stats
        ],
        "hourly_stats": hourly,
        "total_orders": len(HISTORY),
        "total_revenue": sum(o.amount for o in HISTORY),
    }
    system = (
        "You are a retail operations analyst for a coconut drink shop named coconut.kim. "
        "Produce PUNCHY, telegraphic Korean insights — headline style, NOT full polite sentences. "
        "Compress with em-dash '—' (핵심 — 근거) and arrow '→' (문제 → 해결). "
        "Each bullet is a short phrase (ideally under ~25 Korean chars), citing concrete numbers. "
        "AVOID verbose endings like '~이며', '~입니다', '~하세요'. Use noun-ending or imperative-short form. "
        "STYLE EXAMPLES (mimic exactly this tone): "
        "insights → '가장 인기 메뉴는 코코넛 스무디 — 매출의 56%'; "
        "forecast → '매출 피크는 15시대 — 이 시간 인력·재고 보강'; "
        "combos → '스무디 + 워터 함께 주문 2회 — 세트로 묶으면 객단가 상승'; "
        "recommendations → '스무디 의존도 높음 → 다른 메뉴 프로모션으로 분산'. "
        "CRITICAL: 'FACTS_GROUND_TRUTH' is pre-computed and authoritative. NEVER contradict it. "
        "The least-sold item is exactly facts.lowest_seller; the best-seller is facts.top_seller. "
        "Do not recompute or guess rankings — use the given facts. "
        "'item_stats_sorted_by_qty_desc' is sorted by quantity (first=best, last=worst). "
        "INVENTORY LOGIC (never mix these up): a TOP seller (high qty) → '재고 넉넉히 준비' (risk of running out); "
        "a LOW seller (low qty) → '판촉·세트 검토 / 재고 과잉 주의' (it is NOT selling). "
        "Never say a low-seller has '재고 부족'. Never say a top-seller needs '판매 촉진'. "
        "Respond ONLY as JSON with these array-of-string keys: "
        "insights (current status), forecast (demand/staffing/inventory advice), "
        "combos (cross-sell/set-menu ideas), recommendations (action items). "
        "Each array: 2-4 punchy bullets in the style above."
    )
    user = f"SALES_DATA={json.dumps(context, ensure_ascii=False)}"
    result = await llm_json(system, user)
    if result and all(isinstance(result.get(k), list) for k in ("insights", "forecast", "combos", "recommendations")):
        result["ai"] = True
        return result
    base["ai"] = False
    return base


@app.get("/api/ai-status")
async def ai_status():
    """AI 연결 진단 (키 값은 노출 안 함). 문제 원인 파악용."""
    info = {"key_present": bool(OPENAI_API_KEY), "model": OPENAI_MODEL}
    if not OPENAI_API_KEY:
        info["status"] = "no_key (환경변수 OPENAI_API_KEY 미설정 또는 재배포 안 됨)"
        return info
    info["key_prefix"] = OPENAI_API_KEY[:7] + "…"  # sk-xxx… 형태만
    try:
        text = await asyncio.to_thread(_openai_chat_sync, 'Reply with JSON {"ok":true}', "ping")
        info["status"] = "ok ✅ (ChatGPT 정상 작동)"
        info["sample"] = text[:80]
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
            detail = body.get("error", {}).get("message", "")[:200]
        except Exception:
            detail = ""
        info["status"] = f"http_error_{e.code}"
        info["detail"] = detail
    except Exception as e:
        info["status"] = "error"
        info["detail"] = str(e)[:200]
    return info


@app.post("/api/nl-order")
async def nl_order(payload: dict):
    """자연어 주문: 손님 문장 → 메뉴 변환. ChatGPT 있으면 AI, 없으면 키워드 매칭."""
    text = (payload.get("text") or "").strip()[:200]
    if not text:
        raise HTTPException(status_code=400, detail="주문 내용을 입력해주세요.")

    # 초기화 의도 감지 (메뉴 매칭보다 먼저) — 다국어
    reset_kw = [
        "초기화", "비우기", "비워", "리셋", "다 지", "전부 지", "전체 삭제", "모두 삭제", "전부 삭제",
        "clear", "reset", "empty", "xóa", "đặt lại", "hủy", "清空", "重置", "取消", "リセット", "全て削除", "全部消",
    ]
    low = text.lower()
    if any(k.lower() in low for k in reset_kw):
        return {"items": [], "reply": "", "reset": True, "ai": False}

    menu_brief = [
        {"id": m["id"], "name": m["name"], "names": list(m["i18n"].values()), "price": m["price"]}
        for m in MENU
    ]
    system = (
        "You are an ordering assistant for a coconut drink shop. "
        "Map the customer's free-text request (it may be in any language) to menu items. "
        "Respond ONLY as JSON: {\"items\":[{\"id\":\"<menu id>\",\"qty\":<int>}], "
        "\"reply\":\"<one short friendly confirmation in the SAME language as the request>\"}. "
        "Only use ids from the provided menu. If nothing matches, return items=[]."
    )
    user = f"MENU={json.dumps(menu_brief, ensure_ascii=False)}\nREQUEST: {text}"
    result = await llm_json(system, user)
    if result and isinstance(result.get("items"), list):
        items = _resolve_items(result["items"])
        if items:
            return {"items": items, "reply": (result.get("reply") or "")[:120], "ai": True}

    # 폴백: 키워드 매칭
    return {"items": _keyword_match(text), "reply": "", "ai": False}


@app.get("/api/recommend")
async def api_recommend(items: str = ""):
    """업셀 추천: 현재 장바구니와 함께 자주 팔린 메뉴 (통계 기반)."""
    cart_ids = {x for x in items.split(",") if x}
    by_id = {m["id"]: m for m in MENU}

    # 동시 주문 빈도
    score: Dict[str, int] = {}
    for o in HISTORY:
        ids = {it["id"] for it in o.items}
        if cart_ids & ids:
            for other in ids - cart_ids:
                score[other] = score.get(other, 0) + 1
    rec_id = max(score, key=score.get) if score else None

    # 폴백: 전체 인기 메뉴 → 아무 메뉴 (장바구니에 없는 것)
    if not rec_id:
        pop: Dict[str, int] = {}
        for o in HISTORY:
            for it in o.items:
                pop[it["id"]] = pop.get(it["id"], 0) + it["qty"]
        for cid, _ in sorted(pop.items(), key=lambda x: -x[1]):
            if cid not in cart_ids:
                rec_id = cid
                break
    if not rec_id:
        rec_id = next((m["id"] for m in MENU if m["id"] not in cart_ids), None)

    if not rec_id:
        return {"recommend": None}
    m = by_id[rec_id]
    return {"recommend": {"id": m["id"], "name": m["name"], "i18n": m["i18n"], "price": m["price"], "emoji": m["emoji"]}}


@app.get("/admin/export.csv")
async def export_csv():
    """전체 결제 내역을 CSV로 다운로드 (Excel 호환 UTF-8 BOM)."""
    buf = io.StringIO()
    buf.write("﻿")  # Excel에서 한글 깨짐 방지
    w = csv.writer(buf)
    w.writerow(["결제시각", "주문번호", "유형", "픽업번호", "품목", "결제수단", "손님", "금액(원)"])
    method_kr = {"momo": "MoMo", "zalopay": "ZaloPay", "cash": "현금", "card": "카드",
                 "mobilepay": "간편결제", "bank": "계좌이체", "point": "포인트"}
    for o in HISTORY:
        typ = "선주문" if o.order_type == "preorder" else "POS"
        items_str = ", ".join(f"{it['name']} x{it['qty']}" for it in o.items) or o.memo
        w.writerow([
            (o.paid_at or "").replace("T", " "),
            o.order_id, typ, o.pickup_number or "",
            items_str, method_kr.get(o.method, o.method or ""),
            o.payer_name or "", o.amount,
        ])
    filename = f"coconut_orders_{datetime.now(APP_TZ):%Y%m%d_%H%M}.csv"
    return Response(
        content=buf.getvalue().encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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
            "kakao_url": KAKAO_CHANNEL_URL,
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
            "hot_ids": hot_item_ids(),
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


@app.get("/order-qr.png")
async def order_qr_png(request: Request):
    """선주문 진입 QR을 고화질 PNG로 다운로드 (PPT·포스터용)."""
    base = str(request.base_url).rstrip("/")
    png = make_qr_png_bytes(f"{base}/start", box_size=20)  # 인쇄/슬라이드용 고해상도
    return Response(
        content=png,
        media_type="image/png",
        headers={"Content-Disposition": 'attachment; filename="coconut_order_qr.png"'},
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
    js = "window.LANGS=%s;window.I18N=%s;window.PAYMENTS=%s;window.DEFAULT_METHODS=%s;" % (
        json.dumps(LANGS, ensure_ascii=False),
        json.dumps(I18N, ensure_ascii=False),
        json.dumps(PAYMENT_BY_LANG, ensure_ascii=False),
        json.dumps(DEFAULT_METHODS, ensure_ascii=False),
    )
    return Response(content=js, media_type="application/javascript; charset=utf-8")


@app.get("/api/rates")
async def api_rates():
    """실시간 환율 (기준 KRW) + 언어별 통화 매핑."""
    c = await get_rates()
    return {
        "base": "KRW",
        "rates": c["rates"],
        "live": c["live"],
        "currency_by_lang": CURRENCY_BY_LANG,
    }


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
            "stamps": stamp_state(),
            "earned": 1 + (order.amount // STAMP_PER_AMOUNT),
            "kakao_url": KAKAO_CHANNEL_URL,
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

    # POS 주문도 품목 데이터 저장 (분석/CSV용)
    menu_by_id = {m["id"]: m for m in MENU}
    items = []
    for it in (payload.get("items") or []):
        m = menu_by_id.get(it.get("id"))
        if not m:
            continue
        qty = max(0, min(int(it.get("qty", 0)), 99))
        if qty:
            items.append({"id": m["id"], "name": m["name"], "qty": qty, "price": m["price"]})

    order_id = uuid.uuid4().hex[:10].upper()
    order = Order(order_id=order_id, amount=amount, memo=memo, items=items)
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
    method = payload.get("method") or "cash"
    if method not in PAYMENT_METHODS:
        method = "cash"

    # 결제 처리 지연 시뮬레이션 (실제 PG처럼 잠깐 텀)
    await asyncio.sleep(0.6)

    order.status = "paid"
    order.paid_at = now_str()
    order.payer_name = payer_name
    order.method = method
    HISTORY.append(order)
    earned = earn_stamps(order.amount)
    db_save_order(order)

    await broadcast(order_id, {"type": "paid", "order": order.__dict__})
    return {"ok": True, "order": order.__dict__, "stamps": stamp_state(), "earned": earned}


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
    method = payload.get("method") or "cash"
    if method not in PAYMENT_METHODS:
        method = "cash"

    # 결제 처리 지연 시뮬레이션
    await asyncio.sleep(0.6)

    order_id = uuid.uuid4().hex[:10].upper()
    memo = ", ".join(f"{i['name']} x{i['qty']}" for i in items)
    order = Order(
        order_id=order_id,
        amount=amount,
        memo=memo,
        status="paid",
        paid_at=now_str(),
        payer_name=payer_name,
        method=method,
        order_type="preorder",
        pickup_number=next_pickup_number(),
        pickup_status="received",
        items=items,
    )
    ORDERS[order_id] = order
    HISTORY.append(order)
    earn_stamps(amount)
    db_save_order(order)

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
    db_save_order(order)                   # 픽업 상태 변경을 DB에 영구 저장 (없으면 재배포 시 주방에 부활)
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
async def admin_reset(request: Request):
    """결제 내역 및 활성 주문을 전부 초기화 (시연용). ADMIN_PIN 설정 시 암호 일치 필요."""
    if ADMIN_PIN:
        try:
            body = await request.json()
        except Exception:
            body = {}
        if (body or {}).get("pin", "") != ADMIN_PIN:
            raise HTTPException(status_code=403, detail="암호가 올바르지 않습니다.")
    ORDERS.clear()
    HISTORY.clear()
    SUBSCRIBERS.clear()
    PICKUP_COUNTER["n"] = 0
    STAMPS["count"] = 0
    db_clear_orders()
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
