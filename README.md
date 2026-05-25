# QR Pay Demo · 사업계획 시연용 QR 결제 시뮬레이션

가맹점 POS 화면에서 금액을 입력 → QR 생성 → 손님이 모바일로 스캔 → 결제 →
**WebSocket으로 가맹점 화면에 실시간 "결제 완료" 표시**가 뜨는 시연용 웹앱.

> ⚠️ 실제 결제는 일어나지 않습니다. PG 연동 없는 **모의 결제**입니다.

## 설치 & 실행

```bash
cd qr_pay_demo
pip install -r requirements.txt
python main.py
```

콘솔에 LAN IP가 표시됩니다:

```
가맹점 화면 (PC):     http://192.168.x.x:8000/
관리자 (결제 내역):    http://192.168.x.x:8000/admin
```

## 시연 흐름 (3분 데모)

1. **노트북**에서 `http://localhost:8000/` 열기 → 화면 공유
2. 금액 입력 (예: `4,500원`), 메모 (예: `아메리카노 1잔`)
3. **결제 요청** 클릭 → QR 표시
4. **휴대폰 카메라**로 QR 스캔 → 결제 페이지 열림
5. 결제수단 선택, 이름 입력 (선택), **"○○원 결제하기"** 탭
6. 가맹점 화면이 즉시 ✅ **결제 완료** 화면으로 전환 (라이브)
7. `/admin` 으로 이동 → 누적 매출/건수/객단가 보여줌

## 시연 시 주의

- **노트북과 휴대폰이 같은 Wi-Fi에 접속**되어 있어야 합니다.
- 회사·학교 Wi-Fi에서 기기간 통신이 차단되어 있으면 핫스팟을 켜세요.
- 데이터는 메모리에만 저장됩니다. 서버 재시작 시 초기화됩니다.

## 구조

```
main.py              FastAPI 서버 + WebSocket + QR 생성
templates/
  merchant.html      가맹점 POS 화면 (금액 입력, QR, 결제 완료)
  pay.html           손님 모바일 결제 화면
  admin.html         결제 내역 / 매출 요약
requirements.txt
```

## 인터넷 배포 (Render.com 무료)

URL 하나로 어떤 노트북·휴대폰에서든 접속 가능. 발표용으로 가장 안정적.

### 사전 준비
- GitHub 계정 ([github.com](https://github.com))
- Render 계정 ([render.com](https://render.com)) — GitHub로 로그인 가능

### 단계
1. **GitHub에 코드 푸시**
   ```bash
   cd qr_pay_demo
   git init
   git add .
   git commit -m "QR Pay demo"
   git branch -M main
   # GitHub에서 빈 저장소 만든 뒤 URL 복사
   git remote add origin https://github.com/YOUR_USERNAME/qr-pay-demo.git
   git push -u origin main
   ```
2. **Render에서 배포**
   - render.com → **New +** → **Web Service**
   - GitHub 저장소 선택 → **Connect**
   - 설정은 `render.yaml`이 자동으로 잡아줌 (Free 플랜)
   - **Create Web Service** 클릭 → 2~3분 뒤 `https://qr-pay-demo-xxxx.onrender.com` 형태 URL 발급
3. **그 URL을 노트북 브라우저에 띄우고 시연**
   - QR이 자동으로 공개 URL을 가리켜서, 휴대폰이 같은 Wi-Fi에 있을 필요 없음

### Free 플랜 주의사항
- 15분간 요청이 없으면 잠들었다가 다음 접속 시 ~30초 콜드 스타트
- 발표 5분 전에 한 번 URL을 열어 깨워두세요
- 메모리 저장이라 서버가 잠들면 결제 내역도 초기화됨

## 확장 아이디어

- 메뉴 카탈로그 → 메뉴 클릭으로 금액 자동 입력
- 영수증 PDF 다운로드 / 카카오 알림톡 모사
- 일별 매출 차트 (Chart.js)
- 다중 매장 (멀티 테넌트)
- 실제 PG 연동 (토스페이먼츠 테스트 키 등)
