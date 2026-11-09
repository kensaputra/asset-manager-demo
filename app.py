"""Asset Manager demo: track company assets, who holds them, and handover history.

A small Flask + SQLite app. Every name and asset in the bundled database is fake
(see seed.py). Run `python seed.py` once, then `flask --app app run`.
"""
import csv
import io
import os
import secrets
import sqlite3
from datetime import date
from functools import wraps

from flask import (Flask, Response, abort, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CATEGORIES = ["Laptop", "Desktop PC", "Monitor", "Printer", "Network", "CCTV", "Phone", "Furniture"]
STATUSES = {
    "active": "Active",
    "in_storage": "In storage",
    "repair": "Under repair",
    "disposed": "Disposed",
}
PAGE_SIZE = 20


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        DATABASE=os.environ.get("DATABASE") or os.path.join(BASE_DIR, "assets.db"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)

    app.teardown_appcontext(close_db)
    app.jinja_env.globals.update(STATUSES=STATUSES, CATEGORIES=CATEGORIES, csrf_token=csrf_token)
    register_routes(app)
    return app


# --- database -----------------------------------------------------------------

def get_db():
    if "db" not in g:
        from flask import current_app
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# --- auth and CSRF ------------------------------------------------------------

def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def check_csrf():
    sent = request.form.get("csrf", "")
    if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
        abort(400, "Invalid form token. Reload the page and try again.")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if session.get("role") != "admin":
            abort(403, "Only admins can change assets.")
        return view(*args, **kwargs)
    return wrapped


# --- helpers ------------------------------------------------------------------

def month_start():
    return date.today().replace(day=1).isoformat()


def asset_or_404(asset_id):
    row = get_db().execute(
        """SELECT a.*, e.name AS holder_name, e.department AS holder_dept
           FROM assets a LEFT JOIN employees e ON e.id = a.holder_id
           WHERE a.id = ?""",
        (asset_id,),
    ).fetchone()
    if row is None:
        abort(404)
    return row


def read_asset_form(form):
    data = {
        "code": form.get("code", "").strip().upper(),
        "name": form.get("name", "").strip(),
        "category": form.get("category", ""),
        "brand": form.get("brand", "").strip() or None,
        "serial_number": form.get("serial_number", "").strip() or None,
        "location": form.get("location", "").strip(),
        "status": form.get("status", ""),
        "purchased_on": form.get("purchased_on", "").strip() or None,
    }
    errors = []
    if not data["code"]:
        errors.append("Asset code is required.")
    if not data["name"]:
        errors.append("Name is required.")
    if data["category"] not in CATEGORIES:
        errors.append("Pick a category from the list.")
    if data["status"] not in STATUSES:
        errors.append("Pick a status from the list.")
    if not data["location"]:
        errors.append("Location is required.")
    return data, errors


def filtered_assets_query(args):
    where, params = [], []
    q = args.get("q", "").strip()
    if q:
        where.append("(a.code LIKE ? OR a.name LIKE ? OR a.serial_number LIKE ? OR e.name LIKE ?)")
        params += [f"%{q}%"] * 4
    if args.get("category") in CATEGORIES:
        where.append("a.category = ?")
        params.append(args["category"])
    if args.get("status") in STATUSES:
        where.append("a.status = ?")
        params.append(args["status"])
    if args.get("unverified") == "1":
        where.append("(a.last_verified IS NULL OR a.last_verified < ?) AND a.status != 'disposed'")
        params.append(month_start())
    sql = ("FROM assets a LEFT JOIN employees e ON e.id = a.holder_id"
           + (" WHERE " + " AND ".join(where) if where else ""))
    return sql, params


# --- routes -------------------------------------------------------------------

def register_routes(app):

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            check_csrf()
            user = get_db().execute(
                "SELECT * FROM users WHERE username = ?", (request.form.get("username", ""),)
            ).fetchone()
            if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
                session.clear()
                session.update(user=user["username"], role=user["role"])
                nxt = request.args.get("next", "")
                return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dashboard"))
            flash("Wrong username or password.", "error")
        return render_template("login.html")

    @app.post("/logout")
    def logout():
        check_csrf()
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def dashboard():
        db = get_db()
        by_status = dict(db.execute("SELECT status, COUNT(*) FROM assets GROUP BY status").fetchall())
        by_category = db.execute(
            "SELECT category, COUNT(*) AS n FROM assets WHERE status != 'disposed' "
            "GROUP BY category ORDER BY n DESC"
        ).fetchall()
        total = sum(by_status.values())
        unverified = db.execute(
            "SELECT COUNT(*) FROM assets WHERE status != 'disposed' "
            "AND (last_verified IS NULL OR last_verified < ?)", (month_start(),)
        ).fetchone()[0]
        unassigned = db.execute(
            "SELECT COUNT(*) FROM assets WHERE status = 'active' AND holder_id IS NULL"
        ).fetchone()[0]
        recent = db.execute(
            """SELECT h.recorded_at, h.note, a.id AS asset_id, a.code, a.name,
                      f.name AS from_name, t.name AS to_name
               FROM handovers h JOIN assets a ON a.id = h.asset_id
               LEFT JOIN employees f ON f.id = h.from_holder
               LEFT JOIN employees t ON t.id = h.to_holder
               ORDER BY h.recorded_at DESC, h.id DESC LIMIT 8"""
        ).fetchall()
        max_cat = max([r["n"] for r in by_category] or [1])
        return render_template("dashboard.html", total=total, by_status=by_status,
                               by_category=by_category, max_cat=max_cat,
                               unverified=unverified, unassigned=unassigned, recent=recent)

    @app.route("/assets")
    @login_required
    def asset_list():
        db = get_db()
        sql, params = filtered_assets_query(request.args)
        total = db.execute("SELECT COUNT(*) " + sql, params).fetchone()[0]
        page = max(request.args.get("page", 1, type=int), 1)
        rows = db.execute(
            "SELECT a.*, e.name AS holder_name " + sql + " ORDER BY a.code LIMIT ? OFFSET ?",
            params + [PAGE_SIZE, (page - 1) * PAGE_SIZE],
        ).fetchall()
        pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
        args = {k: v for k, v in request.args.items() if k != "page"}
        return render_template("assets.html", rows=rows, total=total, page=page, pages=pages,
                               args=args, month_start=month_start())

    @app.route("/assets/export.csv")
    @login_required
    def asset_export():
        sql, params = filtered_assets_query(request.args)
        rows = get_db().execute(
            "SELECT a.code, a.name, a.category, a.brand, a.serial_number, a.location, a.status, "
            "e.name AS holder, e.department, a.purchased_on, a.last_verified " + sql + " ORDER BY a.code",
            params,
        ).fetchall()
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Code", "Name", "Category", "Brand", "Serial", "Location", "Status",
                         "Holder", "Department", "Purchased", "Last verified"])
        for r in rows:
            writer.writerow([STATUSES.get(v, v) if i == 6 else (v or "") for i, v in enumerate(r)])
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=assets.csv"})

    @app.route("/assets/new", methods=["GET", "POST"])
    @admin_required
    def asset_new():
        data = {"status": "in_storage"}
        if request.method == "POST":
            check_csrf()
            data, errors = read_asset_form(request.form)
            if not errors:
                try:
                    cur = get_db().execute(
                        """INSERT INTO assets (code, name, category, brand, serial_number, location,
                                               status, purchased_on)
                           VALUES (:code, :name, :category, :brand, :serial_number, :location,
                                   :status, :purchased_on)""", data)
                    get_db().commit()
                    flash(f"Asset {data['code']} added.", "ok")
                    return redirect(url_for("asset_detail", asset_id=cur.lastrowid))
                except sqlite3.IntegrityError:
                    errors.append(f"Asset code {data['code']} already exists.")
            for e in errors:
                flash(e, "error")
        return render_template("asset_form.html", asset=data, mode="new")

    @app.route("/assets/<int:asset_id>")
    @login_required
    def asset_detail(asset_id):
        db = get_db()
        asset = asset_or_404(asset_id)
        history = db.execute(
            """SELECT h.*, f.name AS from_name, t.name AS to_name
               FROM handovers h
               LEFT JOIN employees f ON f.id = h.from_holder
               LEFT JOIN employees t ON t.id = h.to_holder
               WHERE h.asset_id = ? ORDER BY h.recorded_at DESC, h.id DESC""",
            (asset_id,),
        ).fetchall()
        employees = db.execute("SELECT * FROM employees ORDER BY name").fetchall()
        return render_template("asset_detail.html", asset=asset, history=history,
                               employees=employees, month_start=month_start())

    @app.route("/assets/<int:asset_id>/edit", methods=["GET", "POST"])
    @admin_required
    def asset_edit(asset_id):
        asset = dict(asset_or_404(asset_id))
        if request.method == "POST":
            check_csrf()
            data, errors = read_asset_form(request.form)
            if not errors:
                try:
                    get_db().execute(
                        """UPDATE assets SET code=:code, name=:name, category=:category, brand=:brand,
                               serial_number=:serial_number, location=:location, status=:status,
                               purchased_on=:purchased_on WHERE id=:id""",
                        {**data, "id": asset_id})
                    get_db().commit()
                    flash("Changes saved.", "ok")
                    return redirect(url_for("asset_detail", asset_id=asset_id))
                except sqlite3.IntegrityError:
                    errors.append(f"Asset code {data['code']} already exists.")
            for e in errors:
                flash(e, "error")
            asset.update(data)
        return render_template("asset_form.html", asset=asset, mode="edit")

    @app.post("/assets/<int:asset_id>/handover")
    @admin_required
    def asset_handover(asset_id):
        check_csrf()
        db = get_db()
        asset = asset_or_404(asset_id)
        raw = request.form.get("to_holder", "")
        to_holder = int(raw) if raw.isdigit() else None
        if to_holder is not None and db.execute(
                "SELECT 1 FROM employees WHERE id = ?", (to_holder,)).fetchone() is None:
            abort(400, "Unknown employee.")
        if to_holder == asset["holder_id"]:
            flash("That person already holds this asset.", "error")
            return redirect(url_for("asset_detail", asset_id=asset_id))
        note = request.form.get("note", "").strip()[:300] or None
        db.execute("INSERT INTO handovers (asset_id, from_holder, to_holder, note, recorded_by) "
                   "VALUES (?, ?, ?, ?, ?)",
                   (asset_id, asset["holder_id"], to_holder, note, session["user"]))
        new_status = "active" if to_holder else "in_storage"
        db.execute("UPDATE assets SET holder_id = ?, status = CASE WHEN status IN ('repair', 'disposed') "
                   "THEN status ELSE ? END WHERE id = ?", (to_holder, new_status, asset_id))
        db.commit()
        flash("Handover recorded.", "ok")
        return redirect(url_for("asset_detail", asset_id=asset_id))

    @app.post("/assets/<int:asset_id>/verify")
    @admin_required
    def asset_verify(asset_id):
        check_csrf()
        asset_or_404(asset_id)
        get_db().execute("UPDATE assets SET last_verified = ? WHERE id = ?",
                         (date.today().isoformat(), asset_id))
        get_db().commit()
        flash("Marked as verified this month.", "ok")
        return redirect(request.form.get("back") if request.form.get("back", "").startswith("/assets")
                        else url_for("asset_detail", asset_id=asset_id))

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    def error_page(err):
        return render_template("error.html", error=err), err.code


app = create_app()
