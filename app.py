# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, session, current_app, Response
from datetime import datetime
import os, sqlite3, uuid, time
from functools import wraps
from movies import MOVIES as BASE_MOVIES, TIMES, HALLS, BOOK_TYPES
from urllib.parse import urlencode
import re
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    APP_TZ = ZoneInfo("Asia/Seoul")
except Exception:
    APP_TZ = None

# -----------------------------
# 공용 유틸
# -----------------------------
TYPE_CODE = {"normal": "1", "group": "2", "teacher": "3"}

def now_iso():
    return (datetime.now(APP_TZ) if APP_TZ else datetime.now()).isoformat()

def db():
    """현재 앱 설정의 DB_PATH를 사용."""
    db_path = current_app.config.get("DB_PATH", os.path.join(current_app.instance_path, "cinema.db"))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def ensure_kv_table():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        """)

def set_setting(key, value):
    ensure_kv_table()
    with db() as conn:
        conn.execute("""
            INSERT INTO settings(key, value)
            VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """, (key, value))
        conn.commit()

def get_setting(key, default=None):
    ensure_kv_table()
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

def make_ticket_id(rtype: str, date_str: str, student_id: str | None) -> str:
    """
    규칙: 티켓구분번호(1/2/3) + YY + MMDD + (student_id; 교사 제외)
    - rtype: normal/group/teacher
    - date_str: 'YYYY-MM-DD'
    - student_id: 학번(교사면 None 또는 '')
    """
    code = TYPE_CODE.get((rtype or "").lower(), "9")
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        yy = dt.strftime("%y")
        mmdd = dt.strftime("%m%d")
    except Exception:
        parts = (date_str or "").split("-")
        yy = (parts[0][-2:] if len(parts) > 0 else "00")
        mm = (parts[1] if len(parts) > 1 else "00").zfill(2)
        dd = (parts[2] if len(parts) > 2 else "00").zfill(2)
        mmdd = f"{mm}{dd}"

    tail = "" if (rtype == "teacher" or not student_id) else str(student_id)
    base = f"{code}{yy}{mmdd}{tail}"

    candidate = base
    n = 1
    with db() as conn:
        while conn.execute("SELECT 1 FROM tickets WHERE id = ? LIMIT 1", (candidate,)).fetchone():
            n += 1
            candidate = f"{base}-{n}"
    return candidate

def normalize_member_names(raw: str) -> str:
    """ '홍길동, 김철수\n이영희' → '홍길동,김철수,이영희' """
    if not raw:
        return ""
    parts = []
    for line in raw.replace("\r", "").split("\n"):
        for p in line.split(","):
            name = p.strip()
            if name:
                parts.append(name)
    seen, uniq = set(), []
    for n in parts:
        if n not in seen:
            uniq.append(n); seen.add(n)
    return ",".join(uniq)

def init_db():
    """필요 테이블 생성/마이그레이션."""
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
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
            except sqlite3.OperationalError:
                pass

        # 추가 칼럼 보강
        ensure_col("tickets", "status", "TEXT NOT NULL DEFAULT 'pending'")
        ensure_col("tickets", "student_id", "TEXT")
        ensure_col("tickets", "student_name", "TEXT")
        ensure_col("tickets", "member_names", "TEXT")  # 단체 인원 이름 저장

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

        ensure_col("movies", "rating", "TEXT")
        ensure_col("movies", "duration", "INTEGER")
        ensure_col("movies", "genre", "TEXT")
        ensure_col("movies", "poster", "TEXT")

def _iter_base_movies():
    # BASE_MOVIES가 list/dict 모두 안전하게 처리
    if isinstance(BASE_MOVIES, dict):
        return BASE_MOVIES.values()
    return BASE_MOVIES

def load_all_movies():
    with db() as conn:
        rows = conn.execute("SELECT * FROM movies ORDER BY title").fetchall()
    added = [dict(r) for r in rows]
    base_map = {}
    for m in _iter_base_movies():
        base_map[m["id"]] = m
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

def has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == col for r in rows)  # r[1] = column name

def get_movie_schedule(movie_id: str):
    """현재 스키마엔 movie_id가 없으므로, 예외 시 빈 리스트 반환."""
    try:
        with db() as conn:
            cur = conn.execute("""
                SELECT date, time, hall
                FROM schedule
                WHERE movie_id=?
                ORDER BY date ASC, time ASC
            """, (movie_id,))
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print("[get_movie_schedule] warn:", e)
        return []

# 규정 기본값
DEFAULT_RULES_DOC = """여기에 현재 쓰고 있는 규정 전문 전체를 그대로 붙여놓으세요.
(처음 1회만 DB에 복사되고, 이후엔 관리자 화면에서 수정)"""

# -----------------------------
# Flask 애플리케이션 생성 (앱 팩토리)
# -----------------------------
def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-nnhs-cinema")
    app.config["ADMIN_PASSWORD"] = os.environ.get("ADMIN_PASSWORD", "nnhs25@")
    app.config["TEACHER_PASSCODE"] = os.environ.get("TEACHER_PASSCODE", "nnhs25@")

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    app.config["DB_PATH"] = os.path.join(app.instance_path, "cinema.db")

    # 필터/컨텍스트
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

    # 미들웨어
    @app.before_request
    def _normalize_params_and_protect():
        if request.endpoint == "tickets":
            tab = (request.args.get("tab") or "normal").lower()
            if tab not in [t.lower() for t in BOOK_TYPES]:
                args = request.args.to_dict(flat=True); args["tab"]="normal"
                return redirect(url_for("tickets", **args))
        if request.path.startswith("/reserve/teacher"):
            if not session.get("teacher_authenticated"):
                next_url = request.full_path if request.query_string else request.path
                return redirect(url_for("teacher_login", next=next_url))
        # 규정/개인정보 동의가 필요할 때 reserve 접근을 rules로 유도
        if request.endpoint == "reserve" and request.method == "GET":
            rtype = request.view_args.get("rtype") if request.view_args else (request.args.get("rtype") or "normal")
            if not session.get("agreed_rules"):
                return redirect(url_for("rules", rtype=rtype))
            if not session.get("agreed_privacy"):
                return redirect(url_for("privacy_agree", rtype=rtype))

    # 권한
    def admin_required(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not session.get("is_admin"):
                flash("관리자 로그인이 필요합니다.", "error")
                return redirect(url_for("admin_login", next=request.path))
            return fn(*args, **kwargs)
        return wrapper

    def teacher_required(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if not session.get("teacher_authenticated"):
                flash("교사 인증 후 이용 가능합니다.", "error")
                next_url = request.full_path if request.query_string else request.path
                return redirect(url_for("teacher_login", next=next_url))
            return view_func(*args, **kwargs)
        return wrapped

    # --------- 공용 라우트 ----------
    @app.route("/healthz")
    def healthz():
        return "ok", 200

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
            if code == current_app.config["TEACHER_PASSCODE"]:
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

    @app.route("/", methods=["GET"], endpoint="home")
    def home():
        movies = load_all_movies()
        featured = movies[0] if movies else None
        return render_template("home.html", movies=movies, featured=featured)

    # url_for('index') 호환
    app.add_url_rule("/", endpoint="index", view_func=home)

    @app.route("/booking", endpoint="booking_mode")
    def booking_mode():
        movie_id = request.args.get("movieId", "")
        return render_template("booking.html", movie_id=movie_id, movies=load_all_movies())

    # --------- 규정/개인정보 동의 + 규정 조회/편집 ----------
    @app.route("/rules", methods=["GET", "POST"], endpoint="rules")
    def rules():
        rtype = (request.values.get("rtype") or "normal").lower()
        text = get_setting("rules_doc", DEFAULT_RULES_DOC)
        if request.method == "POST":
            if request.form.get("agree") == "yes":
                session["agreed_rules"] = True
                return redirect(url_for("privacy_agree", rtype=rtype))
            flash("규정에 동의해야 진행 가능합니다.", "error")
        return render_template("rules.html", text=text, rtype=rtype)

    @app.route("/privacy_agree", methods=["GET", "POST"], endpoint="privacy_agree")
    def privacy_agree():
        rtype = (request.values.get("rtype") or "normal").lower()
        if request.method == "POST":
            if request.form.get("agree") == "yes":
                session["agreed_privacy"] = True
                return redirect(url_for("reserve", rtype=rtype))
            flash("개인정보 수집·이용에 동의해야 예약을 진행할 수 있습니다.", "error")
        return render_template("privacy_agree.html", rtype=rtype)

    @app.route("/rules/doc", methods=["GET"], endpoint="rules_doc")
    def rules_doc():
        rtype = request.args.get("rtype", "normal")
        text = get_setting("rules_doc", DEFAULT_RULES_DOC)
        return render_template("rules_doc.html", text=text, rtype=rtype)

    @app.route("/rules/download", methods=["GET"], endpoint="rules_download")
    def rules_download():
        text = get_setting("rules_doc", DEFAULT_RULES_DOC)
        return Response(
            text,
            mimetype="text/plain; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=nyca_rules.txt"}
        )

    @app.route("/admin/rules", methods=["GET", "POST"], endpoint="admin_rules_edit")
    @admin_required
    def admin_rules_edit():
        if request.method == "POST":
            text = (request.form.get("rules_text") or "").strip()
            if not text:
                flash("규정 내용이 비어 있습니다.", "error")
                return redirect(request.url)
            set_setting("rules_doc", text)
            flash("규정이 저장되었습니다.", "ok")
            return redirect(url_for("rules_doc"))
        text = get_setting("rules_doc", DEFAULT_RULES_DOC)
        return render_template("admin/rules_edit.html", text=text)

    # --------- 예약 ----------
    @app.route("/reserve/<rtype>", methods=["GET", "POST"], endpoint="reserve")
    def reserve(rtype: str):
        rtype = (rtype or "").lower()
        allowed = [t.lower() for t in BOOK_TYPES]
        if rtype not in allowed:
            flash("잘못된 예약 유형입니다.", "error")
            return redirect(url_for("booking_mode"))

        if rtype == "teacher" and not session.get("teacher_authenticated"):
            flash("교사 전용 예약입니다. 인증해 주세요.", "error")
            next_url = request.full_path if request.query_string else request.path
            return redirect(url_for("teacher_login", next=next_url))

        movie_id = request.args.get("movieId") or request.form.get("movie_id")
        all_movies = load_all_movies()
        if not movie_id:
            movie_id = all_movies[0]["id"] if all_movies else None
        movie = get_movie(movie_id) if movie_id else None

        sched = get_schedule_dates()
        if not sched:
            flash("현재 예약 가능한 날짜가 없습니다. (관리자에게 문의)", "error")
            return redirect(url_for("booking_mode"))

        if request.method == "POST":
            form = request.form.to_dict(flat=True)

            date = (form.get("date") or "").strip()
            if not date:
                flash("날짜를 선택하세요.", "error")
                return redirect(request.url)

            sche = get_schedule_for(date)
            if not sche:
                flash("선택한 날짜는 예약할 수 없습니다.", "error")
                return redirect(request.url)

            time_ = sche["time"]
            hall = sche["hall"]

            student_id = (form.get("student_id") or "").strip()
            student_name = (form.get("student_name") or "").strip()

            group_name = None
            group_size = None
            member_names = ""
            teacher_name = None
            class_info = None

            if rtype == "normal":
                if not student_id:
                    flash("학번을 입력하세요.", "error")
                    return redirect(request.url)
                if not student_name:
                    flash("이름을 입력하세요.", "error")
                    return redirect(request.url)

            elif rtype == "group":
                group_name = (form.get("group_name") or "").strip()
                try:
                    group_size = int(form.get("group_size", "0"))
                except Exception:
                    group_size = 0
                member_names = normalize_member_names(form.get("member_names", ""))

            else:  # teacher
                teacher_name = (form.get("teacher_name") or "").strip()
                class_info = (form.get("class_info") or "").strip()
                if not teacher_name:
                    flash("담당 교사 성함을 입력하세요.", "error")
                    return redirect(request.url)
                # 교사용은 학번/이름 없어도 OK
                if not student_id: student_id = None
                if not student_name: student_name = None

            status = "approved" if rtype == "normal" else "pending"
            t_id = make_ticket_id(rtype, date, student_id if rtype != "teacher" else None)

            with db() as conn:
                cols = [
                    "id", "type", "movie_id", "movie_title", "date", "time", "hall",
                    "group_name", "group_size", "teacher_name", "class_info",
                    "student_id", "student_name", "status", "created_at"
                ]
                vals = [
                    t_id, rtype, movie["id"] if movie else None, movie["title"] if movie else None,
                    date, time_, hall,
                    group_name, group_size, teacher_name, class_info,
                    student_id, student_name, status, now_iso()
                ]

                # 단체 인원 이름(member_names) 칼럼이 있으면 같이 저장
                if rtype == "group" and has_column(conn, "tickets", "member_names"):
                    cols.insert(12, "member_names")   # student_id 앞에 삽입
                    vals.insert(12, member_names)

                q_marks = ",".join(["?"] * len(cols))
                conn.execute(f"INSERT INTO tickets ({', '.join(cols)}) VALUES ({q_marks})", tuple(vals))

            return redirect(url_for("ticket_detail", tid=t_id))

        return render_template("reserve.html", rtype=rtype, movie=movie, movies=all_movies, schedule=sched)

    @app.route("/reserve", methods=["GET"])
    def reserve_query_to_path():
        rtype = (request.args.get("rtype") or "").strip().lower()
        movie_id = request.args.get("movieId", "")
        if rtype:
            url = url_for("reserve", rtype=rtype)
            if movie_id: url += f"?movieId={movie_id}"
            return redirect(url, code=302)
        return redirect(url_for("booking_mode"), code=302)

    # --------- 티켓/목록 ----------
    @app.route("/ticket/<tid>", endpoint="ticket_detail")
    def ticket_detail(tid: str):
        with db() as conn:
            row = conn.execute("SELECT * FROM tickets WHERE id=?", (tid,)).fetchone()
        if not row:
            flash("티켓을 찾을 수 없습니다.", "error")
            return redirect(url_for("tickets"))
        return render_template("ticket_detail.html", t=row)

    @app.route("/tickets", endpoint="tickets")
    def tickets():
        tab = (request.args.get("tab") or "normal").lower()
        with db() as conn:
            if tab not in [t.lower() for t in BOOK_TYPES]:
                tab = "normal"
            rows = conn.execute(
                "SELECT * FROM tickets WHERE type=? ORDER BY created_at DESC",
                (tab,)
            ).fetchall()
        return render_template("tickets.html", tab=tab, tickets=rows)

    @app.route("/tickets/<tid>/delete", methods=["POST","OPTIONS"])
    def ticket_delete(tid):
        with db() as conn:
            conn.execute("DELETE FROM tickets WHERE id = ?", (tid,))
        # next=home 이면 홈으로, 기본은 홈으로(요청대로)
        next_where = request.args.get("next", "home").strip()
        if next_where == "home":
            return redirect(url_for("index")), 303
        return redirect(url_for("index")), 303

    # --------- 정보/영화/공지 ----------
    @app.route("/notices", endpoint="notices")
    def notices():
        return render_template("notices.html")

    @app.route("/movie/<movie_id>", methods=["GET"], endpoint="movie_info")
    def movie_info(movie_id):
        mv = get_movie(movie_id)
        if not mv:
            flash("영화 정보를 찾을 수 없습니다.", "error")
            return redirect(url_for("index"))

        schedule = get_movie_schedule(movie_id)
        movie = {
            "id": mv.get("id"),
            "title": mv.get("title", "제목 미상"),
            "poster": mv.get("poster"),
            "genre": mv.get("genre", "-"),
            "rating": mv.get("rating", "-"),
            "runtime": mv.get("duration", mv.get("runtime", "-")),
            "summary": mv.get("summary") or mv.get("synopsis") or "줄거리 정보가 아직 없습니다.",
            "director": mv.get("director", "-"),
            "actors": mv.get("actors", []),
            "year": mv.get("year", ""),
        }
        return render_template("movie_info.html", movie=movie, schedule=schedule)

    @app.route("/info", endpoint="info")
    def info_view():
        return render_template("info.html")

    @app.route("/about", endpoint="about")
    def about():
        return render_template("about.html")

    # --------- 관리자 ----------
    @app.route("/admin/login", methods=["GET","POST"])
    def admin_login():
        if request.method == "POST":
            if request.form.get("password","") == current_app.config["ADMIN_PASSWORD"]:
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
        with db() as conn:
            conn.execute("DELETE FROM tickets WHERE id=?", (tid,))
        flash("예약이 삭제되었습니다.", "ok")
        return redirect(url_for("admin_dashboard"))

    @app.route("/admin/movies", endpoint="admin_movies")
    @admin_required
    def admin_movies():
        all_movies = load_all_movies()
        with db() as conn:
            db_movies = conn.execute("SELECT * FROM movies ORDER BY title").fetchall()
        return render_template("admin/movies.html", movies=all_movies, db_movies=db_movies)

    @app.post("/admin/movies/new")
    @admin_required
    def admin_movies_new():
        title = (request.form.get("title") or "").strip()
        rating = (request.form.get("rating") or "").strip()
        genre = (request.form.get("genre") or "").strip()
        poster = (request.form.get("poster") or "").strip()
        try:
            duration = int(request.form.get("duration","0"))
        except Exception:
            duration = 0
        if not title:
            flash("제목을 입력하세요.", "error"); return redirect(url_for("admin_movies"))
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
        with db() as conn:
            conn.execute("DELETE FROM movies WHERE id=?", (mid,))
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
            try:
                conn.execute("INSERT INTO schedule (date,time,hall) VALUES (?,?,?)", (date,time_,hall))
            except sqlite3.IntegrityError:
                conn.execute("UPDATE schedule SET time=?, hall=? WHERE date=?", (time_,hall,date))
        flash("스케줄이 저장되었습니다.", "ok"); return redirect(url_for("admin_schedule"))

    @app.post("/admin/schedule/<date>/delete")
    @admin_required
    def admin_schedule_delete(date):
        with db() as conn:
            conn.execute("DELETE FROM schedule WHERE date=?", (date,))
        flash("스케줄이 삭제되었습니다.", "ok"); return redirect(url_for("admin_schedule"))

    # --------- 오류/도우미 ----------
    @app.errorhandler(404)
    def handle_404(e):
        try:
            print("\n[404] path=", request.path)
            print("Routes:")
            for rule in app.url_map.iter_rules():
                methods = ",".join(sorted(rule.methods)) if rule.methods else ""
                print(f" - {rule.endpoint:24s} {methods:10s} {rule}")
        except Exception:
            pass
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
                _=url_for("home"); _=url_for("booking_mode")
                _=url_for("notices"); _=url_for("about"); _=url_for("admin_login")
            check("url_for endpoints", _urls)
            def _render_home(): render_template("home.html", movies=load_all_movies())
            def _render_booking(): render_template("booking.html", movie_id="", movies=load_all_movies())
            def _render_reserve_normal():
                ms=load_all_movies(); m=ms[0] if ms else {"id":"unknown","title":"알 수 없는 영화","genre":"-","rating":"-"}
                render_template("reserve.html", rtype="normal", movie=m, movies=ms, schedule=get_schedule_dates())
            check("render home.html", _render_home)
            check("render booking.html", _render_booking)
            check("render reserve.html(normal)", _render_reserve_normal)
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

    # 앱 초기화: DB/규정 기본값
    with app.app_context():
        init_db()
        if get_setting("rules_doc") is None:
            set_setting("rules_doc", DEFAULT_RULES_DOC)

    return app

# 로컬 실행
if __name__ == "__main__":
    app = create_app()
    print("\n=== URL MAP (dev) ===")
    for rule in app.url_map.iter_rules():
        methods = ",".join(sorted(rule.methods)) if rule.methods else ""
        print(f"{rule.endpoint:24s} {methods:10s} {rule}")
    print("===============\n")
    app.run(host="127.0.0.1", port=8000, debug=True)