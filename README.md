
# 남녕시네마 (Flask MVP)

학생자치회 영화 예약 시스템의 최소 기능 제품(MVP)입니다.

## 기능
- 홈: 현재 상영작/상영일 표시, 학번+이름으로 예약
- 티켓: YYMMDD+학번 규칙의 예약번호 발급 및 표시
- 관리자: 영화 추가(제목/상영일/포스터), 예약자 목록 조회, CSV 내보내기
- 시간대: Asia/Seoul 기준

## 빠른 시작
```bash
python -m venv .venv
# Windows PowerShell
. .venv/Scripts/Activate.ps1
# macOS/Linux
# source .venv/bin/activate

pip install -r requirements.txt

# 환경변수 (선택)
# PowerShell: $env:ADMIN_PASSWORD="원하는비번"; $env:SECRET_KEY="랜덤값"
# cmd: set ADMIN_PASSWORD=원하는비번
# Linux/macOS: export ADMIN_PASSWORD=원하는비번
# 포스터 저장 디렉터리 바꾸려면: export POSTER_DIR="static/posters"

python app.py
```

브라우저에서 `http://localhost:5000` 접속

### 관리자 로그인
- 기본 비밀번호: `admin123`
- 환경변수 `ADMIN_PASSWORD`로 변경하세요.

## 데이터
- SQLite 파일: `cinema.db`
- CSV 내보내기: `/admin/export/<movie_id>.csv`

## 구조
```
namnyeong-cinema/
├─ app.py
├─ requirements.txt
├─ templates/
│  ├─ base.html
│  ├─ index.html
│  ├─ ticket.html
│  ├─ admin_login.html
│  └─ admin_dashboard.html
├─ static/
│  ├─ style.css
│  └─ posters/
└─ README.md
```

## TODO / 확장 포인트
- 좌석제 혹은 회차별 정원 관리
- Google 스프레드시트 연동 (현재는 SQLite)
- SSO(학교 계정) 또는 학생 인증(학번 검증) 장치
- 중복/부정 예약 방지(회차당 1인1예약 제약, 블랙리스트 등)
- PWA로 앱 아이콘/오프라인 캐시 제공 → 안드로이드 홈화면 설치
- 서버 배포 (Render, Railway, Fly.io 등 무로/저비용)
```

