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
    Flask, render_template, render_template_string,
    request, redirect, url_for, flash, jsonify, session
)
import psycopg2

APP_TZ = ZoneInfo(os.getenv("APP_TZ", "America/Bogota"))

def today_local() -> date:
    return datetime.now(APP_TZ).date()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "secreto")

# En Render siempre HTTPS -> cookie secure
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=True,
)

AUTH_USERNAME = "COBROS"
AUTH_PASSWORD = "COBROS 2025"  # incluye espacio

def _verify_password(pwd: str) -> bool:
    return hmac.compare_digest(pwd, AUTH_PASSWORD)

def _is_safe_next(target: str) -> bool:
    if not target:
        return False
    u = urlparse(target)
    return not u.netloc and not u.scheme

def login_required(fn):
    @wraps(fn)
    def _wrap(*args, **kwargs):
        if not session.get("auth_ok"):
            nxt = request.path if request.method == "GET" else None
            return redirect(url_for("login", next=nxt))
        return fn(*args, **kwargs)
    return _wrap

RAW_DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()

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
    conn = psycopg2.connect(" ".join(dsn_parts))
    with conn.cursor() as cur:
        cur.execute("SET TIME ZONE %s;", (os.getenv("DB_TZ", "America/Bogota"),))
    return conn

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

# ======== ESQUEMA COMPATIBLE (NO rompe tu info) ========
MIGRATION_SQL = r"""
-- Tabla clientes (ESQUEMA VIEJO)
CREATE TABLE IF NOT EXISTS clientes (
  id SERIAL PRIMARY KEY,
  fecha DATE NOT NULL DEFAULT CURRENT_DATE,
  nombre TEXT NOT NULL,
  monto DOUBLE PRECISION NOT NULL DEFAULT 0,
  porcentaje DOUBLE PRECISION NOT NULL DEFAULT 0,
  deuda DOUBLE PRECISION NOT NULL DEFAULT 0,
  observaciones TEXT
);

-- Tabla base pagos
CREATE TABLE IF NOT EXISTS historial_pagos (
  id SERIAL PRIMARY KEY,
  cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
  pago DOUBLE PRECISION NOT NULL,
  fecha_pago TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

-- View pagos (si tu app/plantillas la usan)
CREATE OR REPLACE VIEW pagos AS
SELECT id, cliente_id, pago, fecha_pago
FROM historial_pagos;

-- Elimina duplicados por cliente/día antes del índice único
WITH d AS (
  SELECT cliente_id, (fecha_pago::date) AS dia, MIN(id) AS keep_id
  FROM historial_pagos
  GROUP BY cliente_id, (fecha_pago::date)
  HAVING COUNT(*) > 1
)
DELETE FROM historial_pagos h
USING d
WHERE h.cliente_id = d.cliente_id
  AND (h.fecha_pago::date) = d.dia
  AND h.id <> d.keep_id;

-- 1 pago por cliente por día (EN LA TABLA)
CREATE UNIQUE INDEX IF NOT EXISTS ux_historial_pagos_cliente_dia
ON historial_pagos (cliente_id, (fecha_pago::date));
"""

def init_schema():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(MIGRATION_SQL)
        conn.commit()

try:
    init_schema()
except Exception as e:
    print("WARN init schema:", repr(e))

# ===== Totales Navbar (seguro) =====
@app.context_processor
def inject_totales():
    deuda_total = 0.0
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT COALESCE(SUM(deuda),0) FROM clientes;")
            deuda_total = float(cur.fetchone()[0] or 0)
    except Exception:
        pass
    return dict(deuda_total=deuda_total, efectivo_hoy=0, total_general=deuda_total, money=money)

@app.get("/health")
def health():
    try:
        conn = get_connection()
        conn.close()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}, 500

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    username = (request.form.get("username") or "")
    password = request.form.get("password") or ""
    next_url = request.args.get("next")

    if not username or not password:
        flash("Usuario y contraseña son obligatorios.", "warning")
        return redirect(url_for("login", next=next_url))

    if username == AUTH_USERNAME and _verify_password(password):
        session["auth_ok"] = True
        session["auth_user"] = username
        flash("Sesión iniciada.", "success")
        if next_url and _is_safe_next(next_url):
            return redirect(next_url)
        return redirect(url_for("home"))

    flash("Credenciales incorrectas.", "warning")
    return redirect(url_for("login", next=next_url))

@app.get("/logout")
def logout():
    session.clear()
    flash("Sesión cerrada.", "info")
    return redirect(url_for("login"))

# ===== HOME: usa columnas VIEJAS (monto, deuda, fecha) =====
@app.route("/")
@login_required
def home():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT id, nombre, monto, deuda, COALESCE(observaciones,'') AS obs, fecha
            FROM clientes
            WHERE deuda > 0
            ORDER BY id DESC;
        """)
        clientes = cur.fetchall()

        cur.execute("SELECT COUNT(*) FROM clientes WHERE deuda > 0;")
        total_clientes = cur.fetchone()[0]

        cur.execute("SELECT COALESCE(SUM(pago),0) FROM historial_pagos;")
        total_recaudado = cur.fetchone()[0]

    return render_template(
        "inicio.html",
        clientes=clientes,
        total_clientes=total_clientes,
        total_recaudado=money(total_recaudado),
        money=money
    )

# ====== Clientes ======
@app.route("/clientes/nuevo", methods=["GET", "POST"])
@login_required
def cliente_nuevo():
    if request.method == "GET":
        return render_template("nuevo.html")

    nombre = (request.form.get("nombre") or "").strip()
    monto_raw = (request.form.get("monto") or "").strip()
    observaciones = (request.form.get("observaciones") or "").strip()
    fecha_str = (request.form.get("fecha") or "").strip()

    if not nombre or not monto_raw:
        flash("Nombre y monto son obligatorios.", "warning")
        return redirect(url_for("cliente_nuevo"))

    try:
        monto = parse_amount(monto_raw)
        if monto < 0:
            raise ValueError
    except Exception:
        flash("El monto debe ser un número válido (>= 0).", "warning")
        return redirect(url_for("cliente_nuevo"))

    try:
        f = date.fromisoformat(fecha_str) if fecha_str else today_local()
    except Exception:
        flash("Fecha inválida (usa AAAA-MM-DD).", "warning")
        return redirect(url_for("cliente_nuevo"))

    with get_connection() as conn, conn.cursor() as cur:
        # deuda inicial = monto
        cur.execute("""
            INSERT INTO clientes (fecha, nombre, monto, deuda, observaciones, porcentaje)
            VALUES (%s, %s, %s, %s, %s, 0);
        """, (f, nombre, monto, monto, observaciones))
        conn.commit()

    flash("Cliente creado correctamente.", "success")
    return redirect(url_for("home"))

@app.route("/clientes/<int:cliente_id>/editar", methods=["GET", "POST"])
@login_required
def cliente_editar(cliente_id):
    with get_connection() as conn, conn.cursor() as cur:
        if request.method == "GET":
            cur.execute("SELECT id, fecha, nombre, monto, deuda, COALESCE(observaciones,'') FROM clientes WHERE id=%s;", (cliente_id,))
            cliente = cur.fetchone()
            if not cliente:
                flash("Cliente no encontrado.", "warning")
                return redirect(url_for("home"))
            return render_template("editar_cliente.html", cliente=cliente)

        nombre = (request.form.get("nombre") or "").strip()
        monto_raw = (request.form.get("monto") or "").strip()
        obs = (request.form.get("observaciones") or "").strip()
        fecha_str = (request.form.get("fecha") or "").strip()

        if not nombre or not monto_raw:
            flash("Nombre y monto son obligatorios.", "warning")
            return redirect(url_for("cliente_editar", cliente_id=cliente_id))

        try:
            monto = parse_amount(monto_raw)
        except Exception:
            flash("Monto inválido.", "warning")
            return redirect(url_for("cliente_editar", cliente_id=cliente_id))

        try:
            f = date.fromisoformat(fecha_str) if fecha_str else today_local()
        except Exception:
            flash("Fecha inválida.", "warning")
            return redirect(url_for("cliente_editar", cliente_id=cliente_id))

        # Recalcula deuda = monto - sum(pagos)
        cur.execute("SELECT COALESCE(SUM(pago),0) FROM historial_pagos WHERE cliente_id=%s;", (cliente_id,))
        total_pagado = float(cur.fetchone()[0] or 0)
        deuda = max(0.0, float(monto) - total_pagado)

        cur.execute("""
            UPDATE clientes
            SET fecha=%s, nombre=%s, monto=%s, deuda=%s, observaciones=%s
            WHERE id=%s;
        """, (f, nombre, monto, deuda, obs, cliente_id))
        conn.commit()

    flash("Cliente actualizado.", "success")
    return redirect(url_for("home"))

@app.post("/clientes/<int:cliente_id>/eliminar")
@login_required
def cliente_eliminar(cliente_id):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM clientes WHERE id=%s;", (cliente_id,))
        conn.commit()
    flash("Cliente eliminado.", "success")
    return redirect(url_for("home"))

# ====== Pagos (1 por día) ======
@app.route("/pagos", methods=["GET"])
@login_required
def pagos_listado():
    cliente_id_filtro = request.args.get("cliente_id", type=int)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, nombre FROM clientes ORDER BY nombre;")
        clientes = cur.fetchall()

        if cliente_id_filtro:
            cur.execute("""
                SELECT h.id, h.pago, h.fecha_pago, '' AS metodo, '' AS nota, c.id, c.nombre
                FROM historial_pagos h
                JOIN clientes c ON c.id = h.cliente_id
                WHERE h.cliente_id=%s
                ORDER BY h.fecha_pago DESC, h.id DESC;
            """, (cliente_id_filtro,))
            pagos = cur.fetchall()

            cur.execute("SELECT id, nombre, monto, deuda, fecha FROM clientes WHERE id=%s;", (cliente_id_filtro,))
            cli = cur.fetchone()
            if not cli:
                flash("Cliente no encontrado.", "warning")
                return redirect(url_for("pagos_listado"))

            cur.execute("SELECT COALESCE(SUM(pago),0) FROM historial_pagos WHERE cliente_id=%s;", (cliente_id_filtro,))
            total_pagado_cli = float(cur.fetchone()[0] or 0)

            resumen = dict(
                id=cli[0],
                nombre=cli[1],
                monto_prestado=float(cli[2] or 0),
                deuda_actual=float(cli[3] or 0),
                fecha_prestamo=cli[4],
                fecha_ultimo_pago=None,
                total_pagado=total_pagado_cli
            )
        else:
            cur.execute("""
                SELECT h.id, h.pago, h.fecha_pago, '' AS metodo, '' AS nota, c.id, c.nombre
                FROM historial_pagos h
                JOIN clientes c ON c.id = h.cliente_id
                ORDER BY h.fecha_pago DESC, h.id DESC;
            """)
            pagos = cur.fetchall()
            resumen = None

        cur.execute("SELECT COALESCE(SUM(pago),0) FROM historial_pagos;")
        total_recaudado = cur.fetchone()[0]

        hoy = today_local()
        cur.execute("SELECT COALESCE(SUM(pago),0) FROM historial_pagos WHERE fecha_pago::date=%s;", (hoy,))
        total_hoy = cur.fetchone()[0]

    return render_template(
        "pagos.html",
        pagos=pagos,
        clientes=clientes,
        total_recaudado=money(total_recaudado),
        total_hoy_pagos=money(total_hoy),
        resumen=resumen,
        cliente_id_filtro=cliente_id_filtro,
        money=money
    )

@app.route("/pagos/nuevo", methods=["POST"])
@login_required
def pago_nuevo():
    cliente_id = request.form.get("cliente_id")
    monto_txt = request.form.get("monto")
    fecha_str = (request.form.get("fecha_pago") or "").strip()

    if not cliente_id or not monto_txt:
        flash("Cliente y monto son obligatorios.", "warning")
        return redirect(url_for("pagos_listado", cliente_id=cliente_id))

    try:
        monto = parse_amount(monto_txt)
        if monto <= 0:
            raise ValueError
    except Exception:
        flash("Monto inválido.", "warning")
        return redirect(url_for("pagos_listado", cliente_id=cliente_id))

    try:
        dia = date.fromisoformat(fecha_str) if fecha_str else today_local()
    except Exception:
        flash("Fecha inválida (AAAA-MM-DD).", "warning")
        return redirect(url_for("pagos_listado", cliente_id=cliente_id))

    with get_connection() as conn, conn.cursor() as cur:
        # valida 1 pago por día (tabla base)
        cur.execute("""
            SELECT 1 FROM historial_pagos
            WHERE cliente_id=%s AND (fecha_pago::date)=%s
            LIMIT 1;
        """, (int(cliente_id), dia))
        if cur.fetchone():
            flash("ESTE CLIENTE YA PAGÓ ESE DÍA", "warning")
            return redirect(url_for("pagos_listado", cliente_id=cliente_id))

        # guarda con timestamp (medianoche)
        dt = datetime(dia.year, dia.month, dia.day, 0, 0, 0)
        cur.execute("""
            INSERT INTO historial_pagos (cliente_id, pago, fecha_pago)
            VALUES (%s, %s, %s);
        """, (int(cliente_id), monto, dt))

        # recalcula deuda cliente
        cur.execute("SELECT monto FROM clientes WHERE id=%s;", (int(cliente_id),))
        monto_total = float(cur.fetchone()[0] or 0)

        cur.execute("SELECT COALESCE(SUM(pago),0) FROM historial_pagos WHERE cliente_id=%s;", (int(cliente_id),))
        pagado = float(cur.fetchone()[0] or 0)

        deuda = max(0.0, monto_total - pagado)
        cur.execute("UPDATE clientes SET deuda=%s WHERE id=%s;", (deuda, int(cliente_id)))

        conn.commit()

    flash("Pago registrado.", "success")
    return redirect(url_for("pagos_listado", cliente_id=cliente_id))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
