# app.py — 남녕시네마 (Flask / 좌석 없음 / 관리자 + 스케줄 + 학번·이름)
from flask import Flask, render_template, request, redirect, url_for, flash, session
from datetime import datetime
import os, sqlite3, uuid, time
from functools import wraps
from movies import MOVIES as BASE_MOVIES, TIMES, HALLS, BOOK_TYPES

try:
    from zoneinfo import ZoneInfo
    APP_TZ = ZoneInfo("Asia/Seoul")
except Exception:
    APP_TZ = None

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "cinema.db")

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = "dev-nnhs-cinema"
app.url_map.strict_slashes = False

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "nnhs2025!")
TEACHER_PASSCODE = os.environ.get("TEACHER_PASSCODE", "namnyeong123")

def now_iso():
    return (datetime.now(APP_TZ) if APP_TZ else datetime.now()).isoformat()

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            movie_id TEXT NOT NULL,
            movie_title TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT,
            hall TEXT,
            seats TEXT,
            group_name TEXT,
            group_size INTEGER,
            teacher_name TEXT,
            class_info TEXT,
            student_id TEXT,
            student_name TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        );
        """)
        def ensure_col(table, col, coltype):
            try: conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
            except sqlite3.OperationalError: pass
        ensure_col("tickets","status","TEXT NOT NULL DEFAULT 'pending'")
        ensure_col("tickets","student_id","TEXT")
        ensure_col("tickets","student_name","TEXT")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS schedule (
            date TEXT PRIMARY KEY,
            time TEXT NOT NULL,
            hall TEXT NOT NULL
        );
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS movies (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            rating TEXT,
            duration INTEGER,
            genre TEXT,
            poster TEXT
        );
        """)
        ensure_col("movies","rating","TEXT")
        ensure_col("movies","duration","INTEGER")
        ensure_col("movies","genre","TEXT")
        ensure_col("movies","poster","TEXT")

init_db()

def load_all_movies():
    with db() as conn:
        rows = conn.execute("SELECT * FROM movies ORDER BY title").fetchall()
    added = [dict(r) for r in rows]
    base_map = {m["id"]: m for m in BASE_MOVIES}
    for m in added:
        base_map[m["id"]] = m
    return list(base_map.values())

def get_movie(mid):
    for m in load_all_movies():
        if m["id"] == mid:
            return m
    ms = load_all_movies()
    return ms[0] if ms else {"id":"unknown","title":"알 수 없는 영화","rating":"-","duration":0,"genre":"-","poster":""}

def get_schedule_dates():
    with db() as conn:
        return conn.execute("SELECT date,time,hall FROM schedule ORDER BY date ASC").fetchall()

def get_schedule_for(date):
    with db() as conn:
        return conn.execute("SELECT date,time,hall FROM schedule WHERE date=?", (date,)).fetchone()

def poster_or_placeholder(url: str) -> str:
    return url or "https://picsum.photos/seed/placeholder/400/600"

@app.template_filter("badge_status")
def badge_status(s):
    return {"pending":"대기","approved":"승인","rejected":"거절"}.get(s,s)

@app.context_processor
def inject_constants():
    return dict(
        BOOK_TYPES=[t.lower() for t in BOOK_TYPES],
        TIMES=TIMES, HALLS=HALLS,
        session=session, url_for=url_for,
        get_movie=get_movie, poster_or_placeholder=poster_or_placeholder
    )

@app.before_request
def _normalize_params_and_protect():
    if request.endpoint == "tickets":
        tab = (request.args.get("tab") or "normal").lower()
        if tab not in BOOK_TYPES:
            args = request.args.to_dict(flat=True); args["tab"]="normal"
            return redirect(url_for("tickets", **args))
    if request.path.startswith("/reserve/teacher"):
        if not session.get("teacher_authenticated"):
            next_url = request.full_path if request.query_string else request.path
            return redirect(url_for("teacher_login", next=next_url))
    if request.path == "/reserve" and (request.args.get("rtype") or "").lower() == "teacher":
        if not session.get("teacher_authenticated"):
            next_url = request.full_path if request.query_string else request.path
            return redirect(url_for("teacher_login", next=next_url))

def teacher_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("teacher_authenticated"):
            flash("교사 인증 후 이용 가능합니다.", "error")
            next_url = request.full_path if request.query_string else request.path
            return redirect(url_for("teacher_login", next=next_url))
        return view_func(*args, **kwargs)
    return wrapped

@app.route("/teacher/login", methods=["GET","POST"])
def teacher_login():
    attempts = session.get("teacher_attempts", 0)
    lock_until = session.get("teacher_lock_until")
    now = int(time.time())
    if lock_until and now < lock_until:
        flash(f"잠시 후 다시 시도하세요. 남은 시간: {lock_until-now}초", "error")
        return render_template("teacher_login.html")
    if request.method == "POST":
        code = (request.form.get("code") or "").strip()
        if code == TEACHER_PASSCODE:
            session["teacher_authenticated"] = True
            session.pop("teacher_attempts", None); session.pop("teacher_lock_until", None)
            flash("교사 인증이 완료되었습니다.", "ok")
            return redirect(request.args.get("next") or url_for("home"))
        attempts += 1; session["teacher_attempts"] = attempts
        if attempts >= 5:
            session["teacher_lock_until"] = now + 300
            flash("틀린 입력이 많아 5분간 잠금되었습니다.", "error")
        else:
            flash(f"인증 코드가 올바르지 않습니다. 남은 시도: {5-attempts}회", "error")
    return render_template("teacher_login.html")

@app.route("/teacher/logout")
def teacher_logout():
    session.pop("teacher_authenticated", None)
    flash("교사 인증이 해제되었습니다.", "info")
    return redirect(url_for("home"))

@app.route("/teacher/booking", endpoint="teacher_booking")
@teacher_required
def teacher_booking():
    return redirect(url_for("booking_mode"))

@app.route("/", methods=["GET"], endpoint="index")
def home():
    return render_template("home.html", movies=load_all_movies())
app.add_url_rule("/", endpoint="home", view_func=home)

@app.route("/booking", endpoint="booking_mode")
def booking_mode():
    movie_id = request.args.get("movieId", "")
    return render_template("booking.html", movie_id=movie_id, movies=load_all_movies())

@app.route("/reserve/<rtype>", methods=["GET","POST"], endpoint="reserve")
def reserve(rtype: str):
    rtype = (rtype or "").lower()
    if rtype not in BOOK_TYPES:
        flash("잘못된 예약 유형입니다.", "error")
        return redirect(url_for("booking_mode"))
    if rtype == "teacher" and not session.get("teacher_authenticated"):
        flash("교사 전용 예약입니다. 인증해 주세요.", "error")
        next_url = request.full_path if request.query_string else request.path
        return redirect(url_for("teacher_login", next=next_url))

    movie_id = request.args.get("movieId") or request.form.get("movie_id")
    if not movie_id:
        allm = load_all_movies(); movie_id = allm[0]["id"] if allm else "unknown"
    movie = get_movie(movie_id)

    sched = get_schedule_dates()
    if not sched:
        flash("현재 예약 가능한 날짜가 없습니다. (관리자에게 문의)", "error")
        return redirect(url_for("booking_mode"))

    if request.method == "POST":
        print("[reserve:POST]", dict(request.form))
        date = (request.form.get("date") or "").strip()
        student_id = (request.form.get("student_id") or "").strip()
        student_name = (request.form.get("student_name") or "").strip()
        if not date: flash("날짜를 선택하세요.", "error"); return redirect(request.url)
        if not student_id: flash("학번을 입력하세요.", "error"); return redirect(request.url)
        if not student_name: flash("이름을 입력하세요.", "error"); return redirect(request.url)

        sche = get_schedule_for(date)
        if not sche:
            flash("선택한 날짜는 예약할 수 없습니다.", "error")
            return redirect(request.url)

        time_ = sche["time"]; hall = sche["hall"]
        group_name = group_size = teacher_name = class_info = None
        if rtype == "group":
            group_name = (request.form.get("group_name") or "").strip()
            try: group_size = int(request.form.get("group_size", "0"))
            except Exception: group_size = 0
            if not group_name or group_size < 5:
                flash("단체명과 5명 이상의 인원을 입력하세요.", "error")
                return redirect(request.url)
        elif rtype == "teacher":
            teacher_name = (request.form.get("teacher_name") or "").strip()
            class_info = (request.form.get("class_info") or "").strip()
            if not teacher_name:
                flash("담당 교사 성함을 입력하세요.", "error")
                return redirect(request.url)

        status = "approved" if rtype == "normal" else "pending"
        t_id = uuid.uuid4().hex[:10]
        with db() as conn:
            conn.execute("""
                INSERT INTO tickets
                (id, type, movie_id, movie_title, date, time, hall,
                 group_name, group_size, teacher_name, class_info,
                 student_id, student_name, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (t_id, rtype, movie["id"], movie["title"], date, time_, hall,
                  group_name, group_size, teacher_name, class_info,
                  student_id, student_name, status, now_iso()))
        print(f"[reserve:OK] ticket={t_id} {date} {time_} {hall} / {student_id} {student_name}")
        return redirect(url_for("ticket_detail", tid=t_id))

    return render_template("reserve.html", rtype=rtype, movie=movie, movies=load_all_movies(), schedule=sched)

@app.route("/reserve", methods=["GET"])
def reserve_query_to_path():
    rtype = (request.args.get("rtype") or "").strip().lower()
    movie_id = request.args.get("movieId", "")
    if rtype:
        url = url_for("reserve", rtype=rtype)
        if movie_id: url += f"?movieId={movie_id}"
        return redirect(url, code=302)
    return redirect(url_for("booking_mode"), code=302)

@app.route("/tickets", endpoint="tickets")
def tickets():
    tab = request.args.get("tab","normal").lower()
    if tab not in BOOK_TYPES: tab = "normal"
    with db() as conn:
        rows = conn.execute("SELECT * FROM tickets WHERE type=? ORDER BY created_at DESC", (tab,)).fetchall()
    return render_template("tickets.html", tab=tab, items=rows)

@app.route("/ticket/<tid>", endpoint="ticket_detail")
def ticket_detail(tid: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM tickets WHERE id=?", (tid,)).fetchone()
    if not row:
        flash("티켓을 찾을 수 없습니다.", "error")
        return redirect(url_for("tickets"))
    return render_template("ticket_detail.html", t=row)

@app.post("/tickets/<tid>/delete")
def ticket_delete(tid: str):
    with db() as conn:
        conn.execute("DELETE FROM tickets WHERE id=?", (tid,))
    flash("티켓이 삭제되었습니다.", "ok")
    return redirect(url_for("tickets", tab=request.args.get("tab","normal")))

@app.route("/notices", endpoint="notices")
def notices():
    notes = ["[10/18] 동아리 상영회 사전 예매 오픈 (선착순)", "[10/20] 단체 예약은 운영진 승인 후 확정됩니다."]
    return render_template("notices.html", notices=notes)

@app.route("/settings", endpoint="settings")
def settings():
    return render_template("settings.html")

@app.route("/about", endpoint="about")
def about():
    return render_template("about.html")

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"): return redirect(url_for("admin_login"))
        return fn(*args, **kwargs)
    return wrapper

@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("password","") == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(url_for("admin_dashboard"))
        flash("비밀번호가 올바르지 않습니다.", "error")
    return render_template("admin/login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin_login"))

@app.route("/admin", endpoint="admin_dashboard")
@admin_required
def admin_dashboard():
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM tickets").fetchone()["c"]
        pending = conn.execute("SELECT COUNT(*) c FROM tickets WHERE status='pending'").fetchone()["c"]
        approved = conn.execute("SELECT COUNT(*) c FROM tickets WHERE status='approved'").fetchone()["c"]
        rejected = conn.execute("SELECT COUNT(*) c FROM tickets WHERE status='rejected'").fetchone()["c"]
        latest = conn.execute("SELECT * FROM tickets ORDER BY created_at DESC LIMIT 20").fetchall()
    return render_template("admin/dashboard.html", total=total, pending=pending, approved=approved, rejected=rejected, latest=latest)

@app.post("/admin/tickets/<tid>/set_status")
@admin_required
def admin_set_status(tid):
    status = request.form.get("status")
    if status not in ("pending", "approved", "rejected"):
        flash("올바르지 않은 상태입니다.", "error")
        return redirect(url_for("admin_dashboard"))
    with db() as conn:
        conn.execute("UPDATE tickets SET status=? WHERE id=?", (status, tid))
    flash("상태가 변경되었습니다.", "ok")
    return redirect(url_for("admin_dashboard"))

@app.post("/admin/tickets/<tid>/delete")
@admin_required
def admin_delete_ticket(tid):
    with db() as conn: conn.execute("DELETE FROM tickets WHERE id=?", (tid,))
    flash("예약이 삭제되었습니다.", "ok")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/movies", endpoint="admin_movies")
@admin_required
def admin_movies():
    all_movies = load_all_movies()
    with db() as conn: db_movies = conn.execute("SELECT * FROM movies ORDER BY title").fetchall()
    return render_template("admin/movies.html", movies=all_movies, db_movies=db_movies)

@app.post("/admin/movies/new")
@admin_required
def admin_movies_new():
    title = (request.form.get("title") or "").strip()
    rating = (request.form.get("rating") or "").strip()
    genre = (request.form.get("genre") or "").strip()
    poster = (request.form.get("poster") or "").strip()
    try: duration = int(request.form.get("duration","0"))
    except Exception: duration = 0
    if not title: flash("제목을 입력하세요.", "error"); return redirect(url_for("admin_movies"))
    mid = uuid.uuid4().hex[:6]
    with db() as conn:
        conn.execute("""INSERT INTO movies (id,title,rating,duration,genre,poster)
                        VALUES (?,?,?,?,?,?)""",
                     (mid, title, rating or "ALL", duration or 90, genre or "기타",
                      poster or f"https://picsum.photos/seed/{mid}/400/600"))
    flash("영화가 추가되었습니다.", "ok")
    return redirect(url_for("admin_movies"))

@app.post("/admin/movies/<mid>/delete")
@admin_required
def admin_movies_delete(mid):
    with db() as conn: conn.execute("DELETE FROM movies WHERE id=?", (mid,))
    flash("영화가 삭제되었습니다.", "ok")
    return redirect(url_for("admin_movies"))

@app.route("/admin/schedule", endpoint="admin_schedule")
@admin_required
def admin_schedule():
    return render_template("admin/schedule.html", schedule=get_schedule_dates())

@app.post("/admin/schedule/new")
@admin_required
def admin_schedule_new():
    date = (request.form.get("date") or "").strip()
    time_ = (request.form.get("time") or "").strip()
    hall = (request.form.get("hall") or "").strip()
    if not (date and time_ and hall):
        flash("날짜/시간/장소를 모두 입력하세요.", "error"); return redirect(url_for("admin_schedule"))
    with db() as conn:
        try: conn.execute("INSERT INTO schedule (date,time,hall) VALUES (?,?,?)", (date,time_,hall))
        except sqlite3.IntegrityError: conn.execute("UPDATE schedule SET time=?, hall=? WHERE date=?", (time_,hall,date))
    flash("스케줄이 저장되었습니다.", "ok"); return redirect(url_for("admin_schedule"))

@app.post("/admin/schedule/<date>/delete")
@admin_required
def admin_schedule_delete(date):
    with db() as conn: conn.execute("DELETE FROM schedule WHERE date=?", (date,))
    flash("스케줄이 삭제되었습니다.", "ok"); return redirect(url_for("admin_schedule"))

@app.errorhandler(404)
def handle_404(e):
    try:
        print("\n[404] path=", request.path)
        print("Routes:")
        for rule in app.url_map.iter_rules():
            methods = ",".join(sorted(rule.methods)) if rule.methods else ""
            print(f" - {rule.endpoint:24s} {methods:10s} {rule}")
    except Exception: pass
    return render_template("notfound.html"), 404

@app.route("/__routes")
def __routes():
    rows = []
    for rule in app.url_map.iter_rules():
        methods = ",".join(sorted(m for m in (rule.methods or set()) if m not in {"HEAD","OPTIONS"}))
        rows.append((rule.rule, rule.endpoint, methods))
    rows.sort()
    html = ["<meta charset='utf-8'><h2>URL Map</h2><table border=1 cellpadding=6 cellspacing=0>"]
    html.append("<tr><th>Rule</th><th>Endpoint</th><th>Methods</th></tr>")
    for r,e,m in rows:
        html.append(f"<tr><td>{r}</td><td>{e}</td><td>{m}</td></tr>")
    html.append("</table>")
    return "".join(html)


@app.route("/_selftest")
def _selftest():
    from markupsafe import escape; import traceback
    results=[]
    def check(title,fn):
        try: fn(); results.append((title,True,"OK"))
        except Exception as e:
            tb=traceback.format_exc(); results.append((title,False,f"{e}\n{tb[:800]}"))
    with app.test_request_context("/"):
        def _urls():
            _=url_for("home"); _=url_for("index"); _=url_for("booking_mode")
            _=url_for("tickets", tab="normal"); _=url_for("notices"); _=url_for("about"); _=url_for("admin_login")
        check("url_for endpoints", _urls)
        def _render_home(): render_template("home.html", movies=load_all_movies())
        def _render_booking(): render_template("booking.html", movie_id="", movies=load_all_movies())
        def _render_reserve_normal():
            ms=load_all_movies(); m=ms[0] if ms else {"id":"unknown","title":"알 수 없는 영화","genre":"-","rating":"-"}
            render_template("reserve.html", rtype="normal", movie=m, movies=ms, schedule=get_schedule_dates())
        check("render home.html", _render_home); check("render booking.html", _render_booking); check("render reserve.html(normal)", _render_reserve_normal)
    rows=[]
    for title,ok,msg in results:
        color="#16a34a" if ok else "#dc2626"
        rows.append(f"<tr><td>{escape(title)}</td><td style='color:{color};font-weight:700'>{'PASS' if ok else 'FAIL'}</td><td><pre style='white-space:pre-wrap'>{escape(msg)}</pre></td></tr>")
    return f"""<html><head><meta charset='utf-8'><title>selftest</title></head>
    <body style="font-family:ui-sans-serif,system-ui;max-width:1000px;margin:20px auto">
      <h2>남녕시네마 자가진단</h2>
      <p>/admin에서 스케줄 1개 이상 등록 후 예매 테스트를 진행하세요.</p>
      <table border="1" cellpadding="6" cellspacing="0"><thead><tr><th>테스트</th><th>결과</th><th>메시지</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
    </body></html>"""

if __name__ == "__main__":
    print("\n=== URL MAP ===")
    for rule in app.url_map.iter_rules():
        methods = ",".join(sorted(rule.methods)) if rule.methods else ""
        print(f"{rule.endpoint:24s} {methods:10s} {rule}")
    print("===============\n")
    app.run(debug=True)
