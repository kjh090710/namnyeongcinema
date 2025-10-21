Param(
  [string]$Root = "."
)

function Ensure-Dir($p) {
  if (-not (Test-Path $p)) { New-Item -ItemType Directory -Path $p | Out-Null }
}

function Ensure-File($path, $content) {
  if (-not (Test-Path $path)) {
    $dir = Split-Path $path -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    $content | Out-File -FilePath $path -Encoding UTF8
  }
}

# 0) 이동
Set-Location $Root

# 1) 필수 디렉터리
Ensure-Dir "./templates"
Ensure-Dir "./templates/admin"
Ensure-Dir "./static"
Ensure-Dir "./static/images"

# 2) app.py / movies.py가 서브폴더에 있으면 루트로 이동
$lostApp = Get-ChildItem -Path . -Recurse -Filter "app.py" | Where-Object { $_.DirectoryName -ne (Get-Location).Path } | Select-Object -First 1
if ($lostApp) { Move-Item -Force $lostApp.FullName "./app.py" }

$lostMovies = Get-ChildItem -Path . -Recurse -Filter "movies.py" | Where-Object { $_.DirectoryName -ne (Get-Location).Path } | Select-Object -First 1
if ($lostMovies) { Move-Item -Force $lostMovies.FullName "./movies.py" }

# 3) 최소 안전본 생성 (기존 파일은 보존)
# base.html
Ensure-File "./templates/base.html" @'
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{% block title %}남녕시네마{% endblock %}</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
  <link rel="stylesheet" href="{{ url_for('static', filename='theme.css') }}">
</head>
<body>
  <header class="header">
    <div class="container" style="display:flex;align-items:center;justify-content:space-between;gap:16px">
      <a class="brand" href="{{ url_for('home') }}">
        <img src="{{ url_for('static', filename='images/logo.png') }}" alt="logo" style="height:32px;border-radius:8px">
        <span>남녕시네마</span>
      </a>
      <nav class="nav">
        <a href="{{ url_for('booking_mode') }}" class="{% if request.endpoint=='booking_mode' %}active{% endif %}">예매</a>
        <a href="{{ url_for('tickets') }}" class="{% if request.endpoint in ['tickets','ticket_detail'] %}active{% endif %}">내 예약</a>
        <a href="{{ url_for('notices') }}" class="{% if request.endpoint=='notices' %}active{% endif %}">공지</a>
        <a href="{{ url_for('about') }}" class="{% if request.endpoint=='about' %}active{% endif %}">소개</a>
      </nav>
    </div>
  </header>
  <main class="container">
    {% for m,c in get_flashed_messages(with_categories=true) %}
      <div class="flash {{ c }}">{{ m }}</div>
    {% endfor %}
    {% block content %}{% endblock %}
  </main>
</body>
</html>
'@

# 다른 템플릿들(없으면만 생성)
Ensure-File "./templates/home.html" @'
{% extends "base.html" %}
{% block title %}홈 · 남녕시네마{% endblock %}
{% block content %}
  <div class="card"><h2 style="margin:0 0 8px">상영작</h2>
    <div class="grid">
      {% for m in movies %}
      <div class="card movie-card">
        <img class="poster" src="{{ m.poster or 'https://picsum.photos/seed/placeholder/400/600' }}" alt="{{ m.title }}">
        <div class="movie-meta">
          <div style="font-weight:700">{{ m.title }}</div>
          <div class="muted">{{ m.genre }} · {{ m.rating }} · {{ m.duration }}분</div>
          <a class="btn primary" style="margin-top:8px" href="{{ url_for('booking_mode') }}?movieId={{ m.id }}">예매하기</a>
        </div>
      </div>
      {% endfor %}
    </div>
  </div>
{% endblock %}
'@

Ensure-File "./templates/booking.html" @'
{% extends "base.html" %}
{% block title %}예매 · 남녕시네마{% endblock %}
{% block content %}
<div class="card">
  <h2 style="margin:0 0 12px">예매 유형</h2>
  <form method="get" action="{{ url_for('booking_mode') }}" class="form">
    <label>영화 선택
      <select name="movieId">
        {% for m in movies %}
        <option value="{{ m.id }}" {% if m.id==movie_id %}selected{% endif %}>{{ m.title }}</option>
        {% endfor %}
      </select>
    </label>
    <div class="pills">
      <a class="btn primary" href="{{ url_for('reserve', rtype='normal') }}?movieId={{ movie_id or (movies[0].id if movies) }}">일반 예매</a>
      <a class="btn ghost" href="{{ url_for('reserve', rtype='group') }}?movieId={{ movie_id or (movies[0].id if movies) }}">단체 예매</a>
      <a class="btn ghost" href="{{ url_for('reserve', rtype='teacher') }}?movieId={{ movie_id or (movies[0].id if movies) }}">교사 전용</a>
    </div>
  </form>
</div>
{% endblock %}
'@

Ensure-File "./templates/reserve.html" @'
{% extends "base.html" %}
{% block title %}예약 · 남녕시네마{% endblock %}
{% block content %}
<div class="card">
  <h2 style="margin:0 0 12px">예약 정보 ({{ rtype }})</h2>
  <form method="post" class="form">
    <input type="hidden" name="movie_id" value="{{ movie.id }}">
    <label>날짜
      <select name="date" required>
        {% for s in schedule %}
        <option value="{{ s['date'] }}">{{ s['date'] }} ({{ s['time'] }} · {{ s['hall'] }})</option>
        {% endfor %}
      </select>
    </label>
    <div class="row cols-2">
      <label>학번 <input class="input" name="student_id" required></label>
      <label>이름 <input class="input" name="student_name" required></label>
    </div>
    {% if rtype == 'group' %}
      <div class="row cols-2">
        <label>단체명 <input class="input" name="group_name"></label>
        <label>인원수(5+) <input class="input" type="number" name="group_size" min="5" value="5"></label>
      </div>
    {% elif rtype == 'teacher' %}
      <div class="row cols-2">
        <label>담당 교사 <input class="input" name="teacher_name"></label>
        <label>반/수업 <input class="input" name="class_info"></label>
      </div>
    {% endif %}
    <div class="pills">
      <button class="btn primary" type="submit">예약 제출</button>
      <a class="btn ghost" href="{{ url_for('booking_mode') }}?movieId={{ movie.id }}">뒤로</a>
    </div>
  </form>
</div>
{% endblock %}
'@

Ensure-File "./templates/tickets.html" @'
{% extends "base.html" %}
{% block title %}내 예약{% endblock %}
{% block content %}
<div class="card">
  <h2 style="margin:0 0 12px">내 예약</h2>
  <div class="pills" style="margin-bottom:10px">
    {% for t in BOOK_TYPES %}
      <a class="btn {% if t==tab %}primary{% else %}ghost{% endif %}" href="{{ url_for('tickets', tab=t) }}">{{ t }}</a>
    {% endfor %}
  </div>
  <table class="table">
    <thead><tr><th>ID</th><th>영화</th><th>일시/장소</th><th>학생</th><th>상태</th><th></th></tr></thead>
    <tbody>
      {% for r in items %}
      <tr>
        <td><a href="{{ url_for('ticket_detail', tid=r['id']) }}">{{ r['id'] }}</a></td>
        <td>{{ r['movie_title'] }}</td>
        <td>{{ r['date'] }} {{ r['time'] }} / {{ r['hall'] }}</td>
        <td>{{ r['student_id'] }} {{ r['student_name'] }}</td>
        <td>{{ r['status'] }}</td>
        <td>
          <form method="post" action="{{ url_for('ticket_delete', tid=r['id']) }}?tab={{ tab }}" onsubmit="return confirm('삭제할까요?')">
            <button class="btn ghost">삭제</button>
          </form>
        </td>
      </tr>
      {% else %}
      <tr><td colspan="6" class="muted">예약이 없습니다.</td></tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
'@

Ensure-File "./templates/ticket_detail.html" @'
{% extends "base.html" %}
{% block title %}예약 상세{% endblock %}
{% block content %}
<div class="card">
  <h2 style="margin:0 0 12px">예약 상세</h2>
  <p><b>ID</b> · {{ t['id'] }}</p>
  <p><b>유형</b> · {{ t['type'] }}</p>
  <p><b>영화</b> · {{ t['movie_title'] }}</p>
  <p><b>일시/장소</b> · {{ t['date'] }} {{ t['time'] }} / {{ t['hall'] }}</p>
  <p><b>학생</b> · {{ t['student_id'] }} {{ t['student_name'] }}</p>
  <div class="pills"><a class="btn ghost" href="{{ url_for('tickets', tab=t['type']) }}">목록</a></div>
</div>
{% endblock %}
'@

Ensure-File "./templates/notices.html" "<div class='card'><h2>공지</h2><ul>{% for n in notices %}<li>{{ n }}</li>{% endfor %}</ul></div>"
Ensure-File "./templates/about.html"   "<div class='card'><h2>소개</h2><p>남녕시네마 예약 시스템</p></div>"
Ensure-File "./templates/settings.html" "<div class='card'><h2>설정</h2><p class='muted'>설정할 항목이 없습니다.</p></div>"
Ensure-File "./templates/notfound.html" "<div class='card'><h2>404</h2><a class='btn primary' href='{{ url_for('home') }}'>홈으로</a></div>"

# 관리자 템플릿 최소본
Ensure-File "./templates/admin/login.html" @'
{% extends "base.html" %}
{% block title %}관리자 로그인{% endblock %}
{% block content %}
<div class="card" style="max-width:420px">
  <h2 style="margin:0 0 12px">관리자 로그인</h2>
  <form method="post" class="form">
    <label>비밀번호 <input class="input" type="password" name="password" required></label>
    <button class="btn primary">로그인</button>
  </form>
</div>
{% endblock %}
'@

Ensure-File "./templates/admin/dashboard.html" "<div class='card'><h2>대시보드</h2><a class='btn primary' href='{{ url_for('admin_movies') }}'>영화 관리</a> <a class='btn ghost' href='{{ url_for('admin_schedule') }}'>스케줄 관리</a></div>"
Ensure-File "./templates/admin/movies.html" "<div class='card'><h2>영화 관리</h2></div>"
Ensure-File "./templates/admin/schedule.html" "<div class='card'><h2>스케줄 관리</h2></div>"

# 4) CSS 최소본
Ensure-File "./static/style.css" @'
/* base styles (safe minimal) */
:root{ --brand:#4277e8; --brand-ink:#fff; --bg:#0b0f17; --panel:#111827; --panel-2:#0e1522; --line:#233047; --text:#e8edf6; --muted:#9fb2cc; --radius:16px; --radius-sm:12px; --shadow:0 8px 24px rgba(0,0,0,.35) }
*{box-sizing:border-box} body{margin:0;font-family:system-ui,'Malgun Gothic',sans-serif;color:var(--text);background:#0b0f17}
a{color:var(--brand);text-decoration:none} .container{max-width:1100px;margin:0 auto;padding:16px}
.header{position:sticky;top:0;background:#10151e;border-bottom:1px solid var(--line)}
.brand{display:flex;gap:10px;align-items:center;color:var(--text);font-weight:800}
.nav{display:flex;gap:8px;flex-wrap:wrap} .nav a{padding:8px 12px;border-radius:999px}
.card{background:#111827;border:1px solid var(--line);border-radius:var(--radius);padding:16px}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(220px,1fr))}
.movie-card .poster{width:100%;aspect-ratio:2/3;border-radius:14px;object-fit:cover;border:1px solid var(--line)}
.btn{display:inline-flex;align-items:center;gap:8px;border-radius:12px;padding:10px 14px;border:1px solid transparent;cursor:pointer}
.btn.primary{background:var(--brand);color:#fff}.btn.ghost{background:transparent;color:var(--text);border:1px solid var(--line)}
.form{display:grid;gap:12px;max-width:640px}.input,select{width:100%;padding:10px;border-radius:10px;border:1px solid var(--line);background:#0c1321;color:var(--text)}
.table{width:100%;border-collapse:collapse}.table th,.table td{padding:10px;border-bottom:1px solid var(--line)}
.pills{display:flex;gap:8px;flex-wrap:wrap}.muted{opacity:.8}
.flash{padding:10px;border-radius:10px;border:1px solid var(--line);background:#0c1321;margin:10px 0}
'@

Ensure-File "./static/theme.css" @'
/* theme override — put your exact design tokens here */
:root{
  --brand:#1a73e8; --bg:#f8f8f8; --panel:#ffffff; --panel-2:#ffffff; --text:#111111; --muted:#666666; --line:#E5E7EB;
  --radius:12px; --radius-sm:10px; --shadow:none;
}
body{background:var(--bg);color:var(--text)}
.header{background:var(--panel);border-bottom:1px solid var(--line)}
.card{background:var(--panel);border:1px solid var(--line);box-shadow:var(--shadow)}
.btn.ghost{border-color:var(--line);color:var(--text)}
.input,select{background:#fff;color:var(--text);border:1px solid var(--line)}
'@

# 5) 로고 자리표시자
if (-not (Test-Path "./static/images/logo.png")) {
  # 간단한 1x1 PNG 생성 (투명) - 실제 로고로 교체 권장
  $pngBytes = [Convert]::FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII=")
  [IO.File]::WriteAllBytes("./static/images/logo.png", $pngBytes)
}

# 6) 최종 구조 출력
Write-Host "`n=== Final Tree ==="
Get-ChildItem -Recurse -File | ForEach-Object { $_.FullName.Replace((Get-Location).Path,'') } | Sort-Object | Write-Host

Write-Host "`nTip:"
Write-Host " - app.py, movies.py는 반드시 루트에 있어야 합니다."
Write-Host " - templates/, static/ 폴더가 꼭 있어야 합니다."
Write-Host " - 로고: static/images/logo.png"
