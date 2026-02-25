# app.py
# -*- coding: utf-8 -*-
import os
import hmac
import calendar
from datetime import date, datetime, timedelta
from urllib.parse import urlparse, parse_qsl
from decimal import Decimal, InvalidOperation
from functools import wraps
from zoneinfo import ZoneInfo

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session
)
import psycopg2

# ================== TZ app ==================
APP_TZ = ZoneInfo(os.getenv("APP_TZ", "America/Bogota"))

def today_local() -> date:
    return datetime.now(APP_TZ).date()

# ================== Flask ==================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "secreto")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=(os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"),
)

# ========= Auth básico =========
USUARIOS = {
    "admin_noche": "noche2025",
    "admin_dia": "dia2025"
}

def _verify_password(username, pwd):
    return username in USUARIOS and hmac.compare_digest(pwd, USUARIOS[username])

def _is_safe_next(target: str) -> bool:
    if not target:
        return False
    u = urlparse(target)
    return not u.netloc and (u.path or "/") and not u.scheme

def login_required(fn):
    @wraps(fn)
    def _wrap(*args, **kwargs):
        if not session.get("auth_ok"):
            nxt = request.path if request.method == "GET" else None
            return redirect(url_for("login", next=nxt))
        return fn(*args, **kwargs)
    return _wrap

# ========= Conexión a PostgreSQL =========
RAW_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://neondb_owner:npg_DqyQpk4iBLh3@ep-still-water-adszkvnv-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require"
).strip()

def _sanitize_url(url: str) -> str:
    url = (url or "").strip().strip('\'"').strip()
    if not url:
        return url
    if "channel_binding=" in url:
        u = urlparse(url)
        params = dict(parse_qsl(u.query))
        params.pop("channel_binding", None)
        q = "&".join(f"{k}={v}" for k, v in params.items()) if params else ""
        url = u._replace(query=q).geturl()
    return url

DATABASE_URL = _sanitize_url(RAW_DATABASE_URL)

def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL no configurada.")
    u = urlparse(DATABASE_URL)
    params = dict(parse_qsl(u.query))
    dsn_parts = [
        f"dbname={u.path.lstrip('/')}",
        f"user={u.username}",
        f"password={u.password}",
        f"host={u.hostname}",
        f"port={u.port or 5432}",
        f"sslmode={params.get('sslmode','require')}",
    ]
    dsn = " ".join(dsn_parts)
    conn = psycopg2.connect(dsn)
    with conn.cursor() as cur:
        cur.execute("SET TIME ZONE %s;", (os.getenv("DB_TZ", "America/Bogota"),))
    return conn

# ========= Utilidades =========
def parse_amount(txt: str) -> float:
    if txt is None:
        raise ValueError("empty")
    t = txt.strip()
    if not t:
        raise ValueError("empty")
    for ch in ["$", "€", "₡", "₲", "₵", "£", "¥", "₿", " "]:
        t = t.replace(ch, "")
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t and "." not in t:
        t = t.replace(",", ".")
    return float(t)

def money(n):
    try:
        return f"${float(n):,.2f}"
    except Exception:
        return n

def end_of_month(d: date) -> date:
    last = calendar.monthrange(d.year, d.month)[1]
    return d.replace(day=last)

# ========= Migración / Esquema =========
MIGRATION_SQL = r"""
CREATE TABLE IF NOT EXISTS clientes (
  id SERIAL PRIMARY KEY,
  nombre TEXT NOT NULL,
  usuario TEXT NOT NULL DEFAULT 'admin_noche',
  monto_prestado NUMERIC(12,2) NOT NULL DEFAULT 0,
  deuda_actual  NUMERIC(12,2) NOT NULL DEFAULT 0,
  observaciones TEXT,
  fecha_prestamo DATE NOT NULL DEFAULT CURRENT_DATE,
  fecha_ultimo_pago DATE,
  archivado BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS pagos (
  id SERIAL PRIMARY KEY,
  cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
  monto NUMERIC(14,2) NOT NULL,
  fecha_pago DATE NOT NULL DEFAULT CURRENT_DATE,
  metodo TEXT,
  nota TEXT
);

CREATE TABLE IF NOT EXISTS efectivo_diario (
  fecha DATE PRIMARY KEY,
  monto NUMERIC(14,2) NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS gastos (
  id SERIAL PRIMARY KEY,
  concepto TEXT NOT NULL,
  monto NUMERIC(14,2) NOT NULL CHECK (monto >= 0),
  fecha DATE NOT NULL DEFAULT CURRENT_DATE,
  nota TEXT
);
"""

def init_schema():
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(MIGRATION_SQL)
    finally:
        conn.close()

try:
    init_schema()
except Exception as e:
    print("WARN init schema:", e)

# ========= Totales para navbar =========
@app.context_processor
def inject_totales():
    deuda_total = 0.0
    efectivo_hoy = 0.0
    user = session.get("auth_user")
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(SUM(deuda_actual),0) FROM clientes WHERE usuario=%s;",
                (user,)
            )
            deuda_total = float(cur.fetchone()[0] or 0)
            hoy = today_local()
            cur.execute(
                "SELECT COALESCE(SUM(monto),0) FROM efectivo_diario WHERE fecha=%s;",
                (hoy,)
            )
            row = cur.fetchone()
            efectivo_hoy = float((row[0] if row else 0) or 0)
    except Exception:
        pass
    total_general = deuda_total + efectivo_hoy
    return dict(
        deuda_total=deuda_total,
        efectivo_hoy=efectivo_hoy,
        total_general=total_general,
        money=money
    )

# ========= Rutas Auth =========
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()
    next_url = request.args.get("next")

    if not username or not password:
        flash("Usuario y contraseña son obligatorios.", "warning")
        return redirect(url_for("login", next=next_url))

    if _verify_password(username, password):
        session["auth_ok"] = True
        session["auth_user"] = username
        flash(f"Sesión iniciada como {username}.", "success")
        if next_url and _is_safe_next(next_url):
            return redirect(next_url)
        return redirect(url_for("home"))
    else:
        flash("Credenciales incorrectas.", "warning")
        return redirect(url_for("login", next=next_url))

@app.get("/logout")
def logout():
    session.clear()
    flash("Sesión cerrada.", "info")
    return redirect(url_for("login"))

# ======================= Rutas Clientes =======================
@app.route("/")
@login_required
def home():
    user = session.get("auth_user")
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                SELECT id, nombre, monto_prestado, deuda_actual,
                       COALESCE(observaciones,'') AS obs,
                       fecha_prestamo, fecha_ultimo_pago
                FROM clientes
                WHERE archivado = FALSE AND usuario=%s
                ORDER BY id DESC;
            """, (user,))
            clientes = cur.fetchall()
        return render_template("inicio.html", clientes=clientes)
    finally:
        conn.close()

@app.route("/clientes/nuevo", methods=["GET", "POST"])
@login_required
def cliente_nuevo():
    if request.method == "GET":
        return render_template("nuevo.html")
    nombre = (request.form.get("nombre") or "").strip()
    monto_raw = (request.form.get("monto_prestado") or "").strip()
    observaciones = (request.form.get("observaciones") or "").strip()
    fecha_str = (request.form.get("fecha_prestamo") or "").strip()
    user = session.get("auth_user")

    if not nombre or not monto_raw:
        flash("Nombre y monto prestado son obligatorios.", "warning")
        return redirect(url_for("cliente_nuevo"))

    try:
        monto = parse_amount(monto_raw)
        if monto < 0:
            raise ValueError
    except Exception:
        flash("Monto inválido.", "warning")
        return redirect(url_for("cliente_nuevo"))

    try:
        fecha_prestamo = date.fromisoformat(fecha_str) if fecha_str else today_local()
    except Exception:
        flash("Fecha inválida.", "warning")
        return redirect(url_for("cliente_nuevo"))

    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO clientes (nombre, monto_prestado, deuda_actual, observaciones, fecha_prestamo, usuario)
                VALUES (%s, %s, %s, %s, %s, %s);
            """, (nombre, monto, monto, observaciones, fecha_prestamo, user))
        flash("Cliente creado correctamente.", "success")
        return redirect(url_for("home"))
    finally:
        conn.close()

@app.route("/clientes/editar/<int:id>", methods=["GET", "POST"])
@login_required
def cliente_editar(id):
    user = session.get("auth_user")
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT id, nombre, monto_prestado, deuda_actual, observaciones, fecha_prestamo FROM clientes WHERE id=%s AND usuario=%s;",
                        (id, user))
            cliente = cur.fetchone()
            if not cliente:
                flash("Cliente no encontrado.", "warning")
                return redirect(url_for("home"))
            if request.method == "GET":
                return render_template("editar.html", cliente=cliente)
            # POST
            nombre = (request.form.get("nombre") or "").strip()
            monto_raw = (request.form.get("monto_prestado") or "").strip()
            deuda_raw = (request.form.get("deuda_actual") or "").strip()
            observaciones = (request.form.get("observaciones") or "").strip()
            if not nombre or not monto_raw or not deuda_raw:
                flash("Todos los campos son obligatorios.", "warning")
                return redirect(url_for("cliente_editar", id=id))
            try:
                monto = parse_amount(monto_raw)
                deuda = parse_amount(deuda_raw)
            except Exception:
                flash("Monto o deuda inválidos.", "warning")
                return redirect(url_for("cliente_editar", id=id))
            cur.execute("""
                UPDATE clientes SET nombre=%s, monto_prestado=%s, deuda_actual=%s, observaciones=%s
                WHERE id=%s AND usuario=%s;
            """, (nombre, monto, deuda, observaciones, id, user))
            flash("Cliente actualizado.", "success")
            return redirect(url_for("home"))
    finally:
        conn.close()

@app.route("/clientes/eliminar/<int:id>", methods=["POST"])
@login_required
def cliente_eliminar(id):
    user = session.get("auth_user")
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("DELETE FROM clientes WHERE id=%s AND usuario=%s;", (id, user))
        flash("Cliente eliminado.", "success")
        return redirect(url_for("home"))
    finally:
        conn.close()

# ======================= Pagos =======================
@app.route("/pagos/nuevo/<int:cliente_id>", methods=["POST"])
@login_required
def pago_nuevo(cliente_id):
    user = session.get("auth_user")
    monto_raw = (request.form.get("monto") or "").strip()
    metodo = (request.form.get("metodo") or "").strip()
    nota = (request.form.get("nota") or "").strip()
    if not monto_raw:
        flash("Monto requerido.", "warning")
        return redirect(url_for("home"))
    try:
        monto = parse_amount(monto_raw)
        if monto <= 0:
            raise ValueError
    except Exception:
        flash("Monto inválido.", "warning")
        return redirect(url_for("home"))

    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT deuda_actual FROM clientes WHERE id=%s AND usuario=%s;", (cliente_id, user))
            row = cur.fetchone()
            if not row:
                flash("Cliente no encontrado.", "warning")
                return redirect(url_for("home"))
            deuda_actual = float(row[0])
            nueva_deuda = max(deuda_actual - monto, 0)
            cur.execute("UPDATE clientes SET deuda_actual=%s, fecha_ultimo_pago=%s WHERE id=%s;", (nueva_deuda, today_local(), cliente_id))
            cur.execute("INSERT INTO pagos (cliente_id, monto, fecha_pago, metodo, nota) VALUES (%s,%s,%s,%s,%s);",
                        (cliente_id, monto, today_local(), metodo, nota))
        flash("Pago registrado.", "success")
        return redirect(url_for("home"))
    finally:
        conn.close()

@app.route("/pagos/deshacer/<int:pago_id>", methods=["POST"])
@login_required
def pago_deshacer(pago_id):
    user = session.get("auth_user")
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                SELECT p.cliente_id, p.monto FROM pagos p
                JOIN clientes c ON c.id = p.cliente_id
                WHERE p.id=%s AND c.usuario=%s;
            """, (pago_id, user))
            row = cur.fetchone()
            if not row:
                flash("Pago no encontrado.", "warning")
                return redirect(url_for("home"))
            cliente_id, monto = row
            cur.execute("DELETE FROM pagos WHERE id=%s;", (pago_id,))
            cur.execute("UPDATE clientes SET deuda_actual=deuda_actual+%s WHERE id=%s;", (monto, cliente_id))
        flash("Pago deshecho.", "info")
        return redirect(url_for("home"))
    finally:
        conn.close()

# ======================= Efectivo diario =======================
@app.route("/efectivo", methods=["GET","POST"])
@login_required
def efectivo():
    if request.method == "GET":
        conn = get_connection()
        try:
            with conn, conn.cursor() as cur:
                cur.execute("SELECT fecha, monto FROM efectivo_diario ORDER BY fecha DESC;")
                filas = cur.fetchall()
            return render_template("efectivo.html", filas=filas)
        finally:
            conn.close()
    # POST para registrar efectivo del día
    monto_raw = (request.form.get("monto") or "").strip()
    if not monto_raw:
        flash("Monto requerido.", "warning")
        return redirect(url_for("efectivo"))
    try:
        monto = parse_amount(monto_raw)
        if monto < 0:
            raise ValueError
    except Exception:
        flash("Monto inválido.", "warning")
        return redirect(url_for("efectivo"))
    hoy = today_local()
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("INSERT INTO efectivo_diario (fecha,monto) VALUES (%s,%s) ON CONFLICT(fecha) DO UPDATE SET monto=efectivo_diario.monto+EXCLUDED.monto;", (hoy,monto))
        flash("Efectivo registrado.", "success")
        return redirect(url_for("efectivo"))
    finally:
        conn.close()

# ======================= Gastos =======================
@app.route("/gastos", methods=["GET","POST"])
@login_required
def gastos():
    if request.method == "GET":
        conn = get_connection()
        try:
            with conn, conn.cursor() as cur:
                cur.execute("SELECT id, concepto, monto, fecha, nota FROM gastos ORDER BY fecha DESC;")
                filas = cur.fetchall()
            return render_template("gastos.html", filas=filas)
        finally:
            conn.close()
    # POST
    concepto = (request.form.get("concepto") or "").strip()
    monto_raw = (request.form.get("monto") or "").strip()
    nota = (request.form.get("nota") or "").strip()
    if not concepto or not monto_raw:
        flash("Concepto y monto requeridos.", "warning")
        return redirect(url_for("gastos"))
    try:
        monto = parse_amount(monto_raw)
        if monto < 0:
            raise ValueError
    except Exception:
        flash("Monto inválido.", "warning")
        return redirect(url_for("gastos"))
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("INSERT INTO gastos (concepto, monto, fecha, nota) VALUES (%s,%s,%s,%s);",
                        (concepto, monto, today_local(), nota))
        flash("Gasto registrado.", "success")
        return redirect(url_for("gastos"))
    finally:
        conn.close()

# ======================= Run =======================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
