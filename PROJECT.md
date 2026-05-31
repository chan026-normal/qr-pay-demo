# coconut.kim — QR 스마트 주문/결제 데모 · 인수인계 문서

> 새 세션에서 이어서 작업할 때 이 문서를 먼저 읽으세요.
> "GitHub의 qr-pay-demo 이어서 작업하자, PROJECT.md 읽어봐" 라고 하면 됩니다.

## 한 줄 소개
사업계획 발표 시연용 **QR 기반 다국어 스마트 주문/결제 데모**.
실제 PG 연동 없는 **모의 결제**. 타깃: **외국인 관광객 + 베트남 Gen Z**.
브랜드명 **coconut.kim**, 결제 브랜드 **킴페이**.

## 배포 / 접속
- 배포 URL: https://qr-pay-demo.onrender.com
- GitHub: chan026-normal/qr-pay-demo (branch: main)
- 호스팅: Render **Web Service (Starter $7/월, 유료 — 콜드 스타트 없음)**
- DB: Render **PostgreSQL (Free)** — ⚠️ **2026-06-30 만료 예정** (만료 전 유료 전환 또는 Neon 이전 필요)
- 모니터링: UptimeRobot (5분 핑 + 다운 알림, 무료)

## 기술 스택
- 백엔드: FastAPI + WebSocket (실시간), Python 3.11
- 프론트: 서버사이드 Jinja2 템플릿 + TailwindCDN + Vanilla JS (빌드 없음)
- DB: SQLAlchemy (DATABASE_URL 있으면 Postgres 영구저장, 없으면 인메모리 폴백)
- AI: OpenAI Chat API (gpt-4o-mini) — 키 없으면 통계/키워드 폴백
- QR/아이콘: qrcode + Pillow (코드로 생성, static 파일 없음)

## 환경변수 (Render → qr-pay-demo → Environment)
| Key | 용도 | 비고 |
|---|---|---|
| `OPENAI_API_KEY` | AI 자연어주문·스마트리포트 | 설정됨. 없으면 통계 폴백 |
| `DATABASE_URL` | 영구 저장 | 설정됨(coconut-db). 없으면 인메모리 |
| `KAKAO_CHANNEL_URL` | 카톡 채널 버튼 링크 | 기본 pf.kakao.com/_PTebX. **Zalo 링크로 교체 가능** |
| `TZ_OFFSET_HOURS` | 매장 표준시 | 기본 9(KST). 베트남이면 7 |
| `OPENAI_MODEL` | 모델명 | 기본 gpt-4o-mini |

## 화면(라우트)
- `/` 가맹점 POS (직원)
- `/order` 손님 셀프 선주문 (메뉴·음성·자연어·업셀·배지) ← PWA start_url
- `/start` QR 스캔 첫 화면 (앱 설치 권유 + 그냥 주문) ← order-qr가 가리키는 곳
- `/track/{id}` 손님 주문 추적 (픽업번호·실시간 상태·스탬프·공유)
- `/kitchen` 주방 디스플레이 (접수→준비중→준비완료 칸반, 실시간)
- `/admin` 관리자 (매출분석·AI리포트·배지설정·CSV·맨아래 초기화)
- `/pay/{id}` 가맹점 QR 결제 화면 (구 흐름, 한국어)
- `/order-qr` 매장 비치용 QR (PPT용: `/order-qr.png` 다운로드)
- `/health` 헬스체크(HEAD 허용, UptimeRobot용)
- API: `/api/order`,`/api/preorder`,`/api/order/{id}/pay|cancel|status`,`/api/recommend`,
  `/api/nl-order`,`/api/insights`,`/api/kitchen/orders`,`/api/admin/reset|badge`,`/api/rates`,`/api/ai-status`(디버그)
- 정적생성: `/i18n.js`,`/manifest.json`,`/icon-{192|512}.png`,`/sw.js`
- WS: `/ws/order/{id}`, `/ws/kitchen`

## 파일 구조
```
main.py                 # 전부 (라우트·DB·AI·환율·스탬프·배지·다국어 I18N)
templates/
  merchant.html         # 가맹점 POS
  order.html            # 손님 셀프주문 (음성·자연어·업셀·배지·전체비우기)
  start.html            # 설치 권유 랜딩
  track.html            # 주문 추적 (스탬프·공유·카톡)
  kitchen.html          # 주방 디스플레이
  admin.html            # 관리자 대시보드
  pay.html              # QR 결제 화면
  order_qr.html         # 선주문 QR 비치용
requirements.txt  render.yaml  runtime.txt  README.md
```

## 완성된 기능
- QR 주문→결제→실시간 동기화(WebSocket)
- 선주문 픽업(셀프주문·픽업번호·주방 칸반·추적)
- 다국어 5개(🇻🇳기본·🇰🇷·🇺🇸·🇨🇳·🇯🇵), 베트남어 기본/최상단
- 실시간 환율(open.er-api.com) — 언어별 통화 표시(KRW 기준 환산)
- PWA(설치, 코코넛 아이콘, 서비스워커, 인앱/삼성인터넷 감지)
- AI: 음성주문(Web Speech API, 무료), 자연어주문(OpenAI), 업셀추천(통계), 스마트운영리포트(OpenAI/통계)
- 매출분석(품목별·시간대별·결제수단), CSV 다운로드, KST 시각
- 스탬프 적립(주문+1, 1만원당+1, 10개=무료음료), 메뉴배지(🔥인기 자동/수동, ✨신메뉴, 👍추천 — 관리자 설정)
- SNS 공유(자기표현 "자랑하기 🥥✨"), 카카오 채널 버튼
- DB 영구저장(주문·배지·스탬프), 결제내역 초기화(맨아래 위험구역)

## 메뉴 (main.py MENU)
- 코코넛 스무디 4,500 / 코코넛 워터 2,500 / 코코넛 칩 3,000 (원)
- 가격·이름·배지는 main.py MENU에서 한 곳 관리

## ⚠️ 다음에 할 일 (타깃 최적화 — 새 세션에서)
우선순위 높은 순:
1. **카카오톡 채널 → Zalo/Instagram 으로 교체** (베트남·관광객은 카톡 안 씀)
   - `KAKAO_CHANNEL_URL` env만 Zalo OA 링크로 바꾸거나, 버튼 라벨/링크 현지화
2. **베트남 모드: 가격 VND 네이티브** (지금은 KRW→환산. 실배포 시 동 단위 메뉴)
3. **결제수단 라벨 현지화** (카드/계좌이체 → MoMo/ZaloPay/현금) — 베트남 심사용
4. 언어 추가(태국·러시아 등) 또는 LLM 자동번역
5. 실제 결제 연동(토스페이먼츠/MoMo/VNPay) — 사업자등록 필요
6. 전화번호 기반 개인 스탬프(지금은 전체 공용)
7. `/api/ai-status` 디버그 엔드포인트 제거(보안)
8. DB 6/30 만료 대비(유료 전환 or Neon 이전)

## 1분 시연 스크립트 (임팩트 최대화)
1. 휴대폰으로 매장 QR 스캔 → /start (베트남어로 뜸)
2. 언어 전환 시연 → 가격이 ₫/¥/$ 로 실시간 변환 (와우1)
3. 🎤 음성 또는 자연어로 주문 ("코코넛 스무디 2개") (와우2)
4. 결제 → 노트북의 /kitchen 화면에 주문 실시간 등장 (와우3)
5. 준비완료 누르면 손님 폰 "픽업하세요!" + 스탬프 적립
- 결제수단·공유버튼은 1분 안엔 건드리지 말 것

## 로컬 실행
```
cd qr_pay_demo
pip install -r requirements.txt
python main.py        # http://localhost:8000
# DB 테스트: DATABASE_URL=sqlite:///./test.db python -m uvicorn main:app
```

## 발표 당일 체크
- 발표 5~10분 전 URL 한 번 열기(유료라 콜드스타트 없지만 보험)
- /admin 맨아래 "결제내역 초기화"로 깨끗하게 시작
- 노트북(/kitchen 띄움) + 휴대폰(주문) 둘 다 인터넷 연결
- 배지 미리 세팅(원하는 메뉴 🔥인기/✨신메뉴)

## 커밋 현황
- 총 46 커밋, 모든 변경 GitHub main에 보존됨
