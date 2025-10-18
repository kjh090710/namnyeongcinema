import os
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from werkzeug.utils import secure_filename

try:
    APP_TZ = ZoneInfo("Asia/Seoul")
except ZoneInfoNotFoundError:
    APP_TZ = timezone(timedelta(hours=9))

def get_db():
    conn = sqlite3.connect(os.environ.get("DATABASE_PATH", "cinema.db"))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS movies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            show_date TEXT NOT NULL,    -- YYYY-MM-DD
            poster_path TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            movie_id INTEGER NOT NULL,
            student_id TEXT NOT NULL,
            student_name TEXT NOT NULL,
            ticket_code TEXT NOT NULL UNIQUE,
            FOREIGN KEY(movie_id) REFERENCES movies(id)
        )
    """)
    conn.commit()
    conn.close()

def get_current_movie(conn):
    # Pick the latest movie by show_date (>= today preferred, otherwise latest past)
    today = datetime.now(APP_TZ).date().isoformat()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM movies 
        ORDER BY date(show_date) >= date(? ) DESC, date(show_date) ASC
    """, (today,))
    row = cur.fetchone()
    return row

def generate_ticket_code(show_date_str, student_id):
    # YYMMDD + student_id
    dt = datetime.fromisoformat(show_date_str)  # naive date
    return dt.strftime("%y%m%d") + str(student_id)

ALLOWED_POSTERS = {"png","jpg","jpeg","webp"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".",1)[1].lower() in ALLOWED_POSTERS

def require_admin():
    return "admin" in session and session["admin"] == True

def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY","dev-secret-change-me")
    app.config["UPLOAD_FOLDER"] = os.environ.get("POSTER_DIR","static/posters")
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    init_db()

    @app.route("/")
    def index():
        conn = get_db()
        movie = get_current_movie(conn)
        conn.close()
        return render_template("index.html", movie=movie)

    @app.route("/reserve", methods=["POST"])
    def reserve():
        student_id = request.form.get("student_id","").strip()
        student_name = request.form.get("student_name","").strip()
        if not (student_id and student_name):
            flash("학번과 이름을 정확히 입력하세요.", "error")
            return redirect(url_for("index"))

        conn = get_db()
        movie = get_current_movie(conn)
        if movie is None:
            conn.close()
            flash("현재 예약 가능한 영화가 없습니다.", "error")
            return redirect(url_for("index"))

        ticket_code = generate_ticket_code(movie["show_date"], student_id)
        now_str = datetime.now(APP_TZ).strftime("%Y-%m-%d %H:%M:%S%z")

        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO reservations (created_at, movie_id, student_id, student_name, ticket_code)
                VALUES (?,?,?,?,?)
            """, (now_str, movie["id"], student_id, student_name, ticket_code))
            conn.commit()
        except sqlite3.IntegrityError:
            # duplicate ticket (same student for same show_date)
            pass
        finally:
            conn.close()

        return redirect(url_for("ticket", code=ticket_code))

    @app.route("/ticket/<code>")
    def ticket(code):
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT r.ticket_code, r.student_id, r.student_name, m.title, m.show_date
            FROM reservations r
            JOIN movies m ON m.id = r.movie_id
            WHERE r.ticket_code = ?
        """, (code,))
        row = cur.fetchone()
        conn.close()
        if not row:
            flash("유효하지 않은 예약 코드입니다.", "error")
            return redirect(url_for("index"))
        return render_template("ticket.html", r=row)

    # ---------- Admin ----------
    @app.route("/admin/login", methods=["GET","POST"])
    def admin_login():
        if request.method == "POST":
            pw = request.form.get("password","")
            if pw == os.environ.get("ADMIN_PASSWORD","admin123"):
                session["admin"] = True
                flash("관리자 로그인 성공", "ok")
                return redirect(url_for("admin_dashboard"))
            flash("비밀번호가 올바르지 않습니다.", "error")
        return render_template("admin_login.html")

    @app.route("/admin/logout")
    def admin_logout():
        session.pop("admin", None)
        flash("로그아웃 완료", "info")
        return redirect(url_for("index"))

    @app.route("/admin", methods=["GET","POST"])
    def admin_dashboard():
        if not require_admin():
            return redirect(url_for("admin_login"))
        conn = get_db()
        cur = conn.cursor()

        if request.method == "POST":
            title = request.form.get("title","").strip()
            show_date = request.form.get("show_date","").strip()  # YYYY-MM-DD
            poster_path = None
            file = request.files.get("poster")
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                # ensure unique
                name, ext = os.path.splitext(filename)
                filename = f"{name}_{int(datetime.now().timestamp())}{ext}"
                save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                file.save(save_path)
                poster_path = save_path.replace("\\","/")

            if title and show_date:
                cur.execute("INSERT INTO movies (title, show_date, poster_path) VALUES (?,?,?)",
                            (title, show_date, poster_path))
                conn.commit()
                flash("영화가 추가되었습니다.", "ok")
            else:
                flash("제목과 상영일을 입력하세요.", "error")

        # list movies & counts
        cur.execute("""
            SELECT m.*, COUNT(r.id) AS rcount
            FROM movies m
            LEFT JOIN reservations r ON r.movie_id = m.id
            GROUP BY m.id
            ORDER BY date(m.show_date) DESC
        """)
        movies = cur.fetchall()
        conn.close()
        return render_template("admin_dashboard.html", movies=movies)

    @app.route("/admin/reservations/<int:movie_id>")
    def admin_reservations(movie_id):
        if not require_admin():
            return redirect(url_for("admin_login"))
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT r.*, m.title, m.show_date
            FROM reservations r
            JOIN movies m ON m.id = r.movie_id
            WHERE m.id = ?
            ORDER BY r.created_at ASC
        """, (movie_id,))
        rows = cur.fetchall()
        conn.close()
        return render_template("reservations.html", rows=rows)

    @app.route("/admin/export/<int:movie_id>.csv")
    def admin_export(movie_id):
        if not require_admin():
            return redirect(url_for("admin_login"))
        # export CSV
        import csv, io
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT r.created_at, r.student_id, r.student_name, r.ticket_code, m.title, m.show_date
            FROM reservations r
            JOIN movies m ON m.id = r.movie_id
            WHERE m.id = ?
            ORDER BY r.created_at ASC
        """, (movie_id,))
        rows = cur.fetchall()
        conn.close()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["created_at","student_id","student_name","ticket_code","movie_title","show_date"])
        for r in rows:
            writer.writerow([r["created_at"], r["student_id"], r["student_name"], r["ticket_code"], r["title"], r["show_date"]])

        mem = io.BytesIO(output.getvalue().encode("utf-8-sig"))
        mem.seek(0)
        fname = f"reservations_{movie_id}.csv"
        return send_file(mem, as_attachment=True, download_name=fname, mimetype="text/csv")

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)
