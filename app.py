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


# ================== TZ app ==================
APP_TZ = ZoneInfo(os.getenv("APP_TZ", "America/Bogota"))

def today_local() -> date:
    return datetime.now(APP_TZ).date()

def end_of_month(d: date) -> date:
    last = calendar.monthrange(d.year, d.month)[1]
    return d.replace(day=last)


# ================== Flask ==================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "secreto")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=(os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"),
)


# ========= Auth MUY SIMPLE (hardcode) =========
AUTH_USERNAME = "COBROS"
AUTH_PASSWORD = "COBROS 2025"  # OJO: incluye espacio

def _verify_password(pwd: str) -> bool:
    return hmac.compare_digest(pwd, AUTH_PASSWORD)

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


# ========= Conexión DB =========
RAW_DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

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


# ========= Utils =========
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

def _parse_amount_relajado(txt: str):
    if txt is None:
        return None
    t = txt.strip()
    if not t:
        return None
    for ch in ["$", "€", "₡", "₲", "₵", "£", "¥", "₿", " "]:
        t = t.replace(ch, "")
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t and "." not in t:
        t = t.replace(",", ".")
    return t


# ========= Esquema mínimo (SIN romper tu BD vieja) =========
# - No crea tabla "pagos" (porque hoy es una VIEW)
# - Crea/asegura historial_pagos, gastos, efectivo_diario
MIGRATION_SQL = r"""
CREATE TABLE IF NOT EXISTS clientes (
  id SERIAL PRIMARY KEY,
  fecha DATE,
  nombre TEXT,
  monto DOUBLE PRECISION,
  porcentaje DOUBLE PRECISION,
  deuda DOUBLE PRECISION,
  observaciones TEXT
);

CREATE TABLE IF NOT EXISTS historial_pagos (
  id SERIAL PRIMARY KEY,
  cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
  pago DOUBLE PRECISION NOT NULL,
  fecha_pago TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS efectivo_diario (
  fecha DATE,
  monto NUMERIC(14,2) NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS gastos (
  id SERIAL PRIMARY KEY,
  concepto TEXT NOT NULL,
  monto NUMERIC(14,2) NOT NULL CHECK (monto >= 0),
  fecha DATE NOT NULL DEFAULT CURRENT_DATE,
  nota TEXT
);

CREATE INDEX IF NOT EXISTS idx_gastos_fecha ON gastos(fecha);

-- Índice único (1 pago por cliente por día) sobre la TABLA REAL
-- Puede fallar si ya hay duplicados por día; por eso el init_schema lo captura.
CREATE UNIQUE INDEX IF NOT EXISTS ux_historial_cliente_dia
ON public.historial_pagos (cliente_id, (fecha_pago::date));
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
    # Si hay duplicados históricos, este índice puede fallar; no tumba la app.
    print("WARN init schema:", e)


# ========= Recalcular deuda (robusto, sin triggers) =========
def recalc_deuda(conn, cliente_id: int):
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(monto,0) FROM clientes WHERE id=%s;", (cliente_id,))
        row = cur.fetchone()
        if not row:
            return
        monto = float(row[0] or 0)

        cur.execute("SELECT COALESCE(SUM(pago),0) FROM historial_pagos WHERE cliente_id=%s;", (cliente_id,))
        total_pagado = float(cur.fetchone()[0] or 0)

        deuda_nueva = max(0.0, monto - total_pagado)
        cur.execute("UPDATE clientes SET deuda=%s WHERE id=%s;", (deuda_nueva, cliente_id))


# ========= Totales visibles en el navbar =========
@app.context_processor
def inject_totales():
    deuda_total = 0.0
    efectivo_hoy = 0.0
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT COALESCE(SUM(deuda),0) FROM clientes;")
            deuda_total = float(cur.fetchone()[0] or 0)

            hoy = today_local()
            cur.execute("SELECT COALESCE(SUM(monto),0) FROM efectivo_diario WHERE fecha = %s;", (hoy,))
            efectivo_hoy = float(cur.fetchone()[0] or 0)
    except Exception:
        pass

    total_general = deuda_total + efectivo_hoy
    return dict(
        deuda_total=deuda_total,
        efectivo_hoy=efectivo_hoy,
        total_general=total_general,
        money=money
    )


# ========= Salud =========
@app.get("/health")
def health():
    try:
        conn = get_connection()
        conn.close()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}, 500

@app.get("/dbcheck")
def dbcheck():
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1;")
            one = cur.fetchone()[0]
        return jsonify(db="ok" if one == 1 else "fail")
    except Exception as e:
        return jsonify(db="error", detail=str(e)), 500


# ========= Auth Rutas =========
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
    else:
        flash("Credenciales incorrectas.", "warning")
        return redirect(url_for("login", next=next_url))

@app.get("/logout")
def logout():
    session.clear()
    flash("Sesión cerrada.", "info")
    return redirect(url_for("login"))


# ========= Rutas =========

# Home: clientes con deuda activa (esquema viejo)
@app.route("/")
@login_required
def home():
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                SELECT
                  c.id,                                  -- [0]
                  c.nombre,                              -- [1]
                  COALESCE(c.monto,0) AS prestado,       -- [2]
                  COALESCE(c.deuda,0) AS deuda,          -- [3]
                  COALESCE(c.observaciones,'') AS obs,   -- [4]
                  c.fecha AS fecha_prestamo,             -- [5]
                  sub.ultimo_pago                        -- [6]
                FROM clientes c
                LEFT JOIN (
                  SELECT cliente_id, MAX(fecha_pago)::date AS ultimo_pago
                  FROM historial_pagos
                  GROUP BY cliente_id
                ) sub ON sub.cliente_id = c.id
                WHERE COALESCE(c.deuda,0) > 0
                ORDER BY c.id DESC;
            """)
            clientes = cur.fetchall()

            cur.execute("SELECT COUNT(*) FROM clientes WHERE COALESCE(deuda,0) > 0;")
            total_clientes = cur.fetchone()[0]

            cur.execute("SELECT COALESCE(SUM(pago),0) FROM historial_pagos;")
            total_recaudado = cur.fetchone()[0]

        return render_template(
            "inicio.html",
            clientes=clientes,
            total_clientes=total_clientes,
            total_recaudado=money(total_recaudado),
        )
    finally:
        conn.close()


# -------- Clientes "pagados" (deuda = 0) --------
@app.get("/clientes/archivados")
@login_required
def clientes_archivados():
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                SELECT
                  c.id, c.nombre,
                  COALESCE(c.monto,0) AS prestado,
                  COALESCE(c.deuda,0) AS deuda,
                  c.fecha AS fecha_prestamo,
                  sub.ultimo_pago
                FROM clientes c
                LEFT JOIN (
                  SELECT cliente_id, MAX(fecha_pago)::date AS ultimo_pago
                  FROM historial_pagos
                  GROUP BY cliente_id
                ) sub ON sub.cliente_id = c.id
                WHERE COALESCE(c.deuda,0) <= 0
                ORDER BY c.id DESC;
            """)
            filas = cur.fetchall()
        return render_template("clientes_archivados.html", filas=filas, money=money)
    finally:
        conn.close()


@app.post("/clientes/<int:cliente_id>/eliminar_def")
@login_required
def cliente_eliminar_def(cliente_id):
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("DELETE FROM clientes WHERE id=%s;", (cliente_id,))
        flash("Cliente eliminado definitivamente.", "success")
        return redirect(url_for("clientes_archivados"))
    finally:
        conn.close()


# -------- Clientes CRUD --------
@app.route("/clientes/nuevo", methods=["GET", "POST"])
@login_required
def cliente_nuevo():
    if request.method == "GET":
        return render_template("nuevo.html")

    nombre = (request.form.get("nombre") or "").strip()
    monto_raw = (request.form.get("monto_prestado") or "").strip()
    observaciones = (request.form.get("observaciones") or "").strip()
    fecha_str = (request.form.get("fecha_prestamo") or "").strip()

    if not nombre or not monto_raw:
        flash("Nombre y monto prestado son obligatorios.", "warning")
        return redirect(url_for("cliente_nuevo"))

    try:
        monto = parse_amount(monto_raw)
        if monto < 0:
            raise ValueError
    except Exception:
        flash("El monto prestado debe ser un número válido (>= 0).", "warning")
        return redirect(url_for("cliente_nuevo"))

    try:
        fecha_prestamo = date.fromisoformat(fecha_str) if fecha_str else today_local()
    except Exception:
        flash("Fecha de préstamo inválida (usa AAAA-MM-DD).", "warning")
        return redirect(url_for("cliente_nuevo"))

    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO clientes (fecha, nombre, monto, deuda, observaciones)
                VALUES (%s, %s, %s, %s, %s);
            """, (fecha_prestamo, nombre, monto, monto, observaciones))
        flash("Cliente creado correctamente.", "success")
        return redirect(url_for("home"))
    finally:
        conn.close()


@app.route("/clientes/<int:cliente_id>/editar", methods=["GET", "POST"])
@login_required
def cliente_editar(cliente_id):
    conn = get_connection()
    try:
        if request.method == "GET":
            with conn, conn.cursor() as cur:
                cur.execute("""
                    SELECT id, nombre, COALESCE(monto,0), COALESCE(deuda,0), COALESCE(observaciones,''), fecha
                    FROM clientes WHERE id=%s;
                """, (cliente_id,))
                cliente = cur.fetchone()
                if not cliente:
                    flash("Cliente no encontrado.", "warning")
                    return redirect(url_for("home"))
            return render_template("editar_cliente.html", cliente=cliente)

        nombre = (request.form.get("nombre") or "").strip()
        monto_raw = (request.form.get("monto_prestado") or "").strip()
        observaciones = (request.form.get("observaciones") or "").strip()
        fecha_str = (request.form.get("fecha_prestamo") or "").strip()

        if not nombre or not monto_raw:
            flash("Nombre y monto prestado son obligatorios.", "warning")
            return redirect(url_for("cliente_editar", cliente_id=cliente_id))

        try:
            monto = parse_amount(monto_raw)
            if monto < 0:
                raise ValueError
        except Exception:
            flash("El monto prestado debe ser un número válido (>= 0).", "warning")
            return redirect(url_for("cliente_editar", cliente_id=cliente_id))

        try:
            fecha_prestamo = date.fromisoformat(fecha_str) if fecha_str else today_local()
        except Exception:
            flash("Fecha de préstamo inválida (usa AAAA-MM-DD).", "warning")
            return redirect(url_for("cliente_editar", cliente_id=cliente_id))

        with conn, conn.cursor() as cur:
            cur.execute("""
                UPDATE clientes
                SET nombre=%s, monto=%s, observaciones=%s, fecha=%s
                WHERE id=%s;
            """, (nombre, monto, observaciones, fecha_prestamo, cliente_id))

            # Recalcular deuda con base en pagos existentes
            recalc_deuda(conn, cliente_id)

        flash("Cliente actualizado.", "success")
        return redirect(url_for("home"))
    finally:
        conn.close()


@app.route("/clientes/<int:cliente_id>/eliminar", methods=["POST"])
@login_required
def cliente_eliminar(cliente_id):
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("DELETE FROM clientes WHERE id=%s;", (cliente_id,))
        flash("Cliente eliminado.", "success")
        return redirect(url_for("home"))
    finally:
        conn.close()


# -------- Pagos --------
@app.route("/pagos", methods=["GET"])
@login_required
def pagos_listado():
    cliente_id_filtro = request.args.get("cliente_id", type=int)

    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            # clientes para select
            cur.execute("SELECT id, nombre FROM clientes ORDER BY nombre;")
            clientes = cur.fetchall()

            if cliente_id_filtro:
                cur.execute("""
                    SELECT
                      p.id, p.pago, p.fecha_pago,
                      NULL::text AS metodo,
                      NULL::text AS nota,
                      c.id AS cliente_id,
                      c.nombre
                    FROM historial_pagos p
                    JOIN clientes c ON c.id = p.cliente_id
                    WHERE p.cliente_id = %s
                    ORDER BY p.fecha_pago DESC, p.id DESC;
                """, (cliente_id_filtro,))
                pagos = cur.fetchall()

                cur.execute("""
                    SELECT id, nombre, COALESCE(monto,0), COALESCE(deuda,0), fecha
                    FROM clientes
                    WHERE id = %s;
                """, (cliente_id_filtro,))
                cli = cur.fetchone()
                if not cli:
                    flash("Cliente no encontrado.", "warning")
                    return redirect(url_for("pagos_listado"))

                cur.execute("SELECT COALESCE(SUM(pago),0) FROM historial_pagos WHERE cliente_id = %s;", (cliente_id_filtro,))
                total_pagado_cli = float(cur.fetchone()[0] or 0)

                cur.execute("SELECT MAX(fecha_pago)::date FROM historial_pagos WHERE cliente_id=%s;", (cliente_id_filtro,))
                ultimo_pago = cur.fetchone()[0]

                resumen = dict(
                    id=cli[0],
                    nombre=cli[1],
                    monto_prestado=float(cli[2] or 0),
                    deuda_actual=float(cli[3] or 0),
                    fecha_prestamo=cli[4],
                    fecha_ultimo_pago=ultimo_pago,
                    total_pagado=total_pagado_cli
                )
            else:
                cur.execute("""
                    SELECT
                      p.id, p.pago, p.fecha_pago,
                      NULL::text AS metodo,
                      NULL::text AS nota,
                      c.id AS cliente_id,
                      c.nombre
                    FROM historial_pagos p
                    JOIN clientes c ON c.id = p.cliente_id
                    ORDER BY p.fecha_pago DESC, p.id DESC;
                """)
                pagos = cur.fetchall()
                resumen = None

            cur.execute("SELECT COALESCE(SUM(pago),0) FROM historial_pagos;")
            total_recaudado = cur.fetchone()[0]

            hoy = today_local()
            cur.execute("SELECT COALESCE(SUM(pago),0) FROM historial_pagos WHERE fecha_pago::date = %s;", (hoy,))
            total_hoy_pagos = cur.fetchone()[0]

        return render_template(
            "pagos.html",
            pagos=pagos,
            clientes=clientes,
            total_recaudado=money(total_recaudado),
            total_hoy_pagos=money(total_hoy_pagos),
            resumen=resumen,
            cliente_id_filtro=cliente_id_filtro
        )
    finally:
        conn.close()


@app.route("/pagos/nuevo", methods=["POST"])
@login_required
def pago_nuevo():
    cliente_id = request.form.get("cliente_id")
    monto = request.form.get("monto")
    fecha_str = (request.form.get("fecha_pago") or "").strip()

    if not cliente_id or not monto:
        flash("Cliente y monto son obligatorios.", "warning")
        return redirect(url_for("pagos_listado", cliente_id=cliente_id))

    try:
        monto_norm = parse_amount(monto)
        if monto_norm <= 0:
            raise ValueError
    except Exception:
        flash("Monto inválido.", "warning")
        return redirect(url_for("pagos_listado", cliente_id=cliente_id))

    try:
        fecha_pago = date.fromisoformat(fecha_str) if fecha_str else today_local()
    except Exception:
        flash("Fecha de pago inválida (usa AAAA-MM-DD).", "warning")
        return redirect(url_for("pagos_listado", cliente_id=cliente_id))

    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            # 1 pago por cliente por día
            cur.execute("""
                SELECT 1
                FROM historial_pagos
                WHERE cliente_id = %s AND fecha_pago::date = %s
                LIMIT 1;
            """, (int(cliente_id), fecha_pago))
            if cur.fetchone():
                flash("ESTE CLIENTE YA PAGO HOY", "warning")
                return redirect(url_for("pagos_listado", cliente_id=cliente_id))

            # Insert
            cur.execute("""
                INSERT INTO historial_pagos (cliente_id, pago, fecha_pago)
                VALUES (%s, %s, (%s::date)::timestamp)
                RETURNING id;
            """, (int(cliente_id), monto_norm, fecha_pago))

            # Recalcular deuda exacta (evita errores acumulados)
            recalc_deuda(conn, int(cliente_id))

        flash("Pago registrado.", "success")
        return redirect(url_for("pagos_listado", cliente_id=cliente_id))
    finally:
        conn.close()


@app.route("/pagos/<int:pago_id>/editar", methods=["GET", "POST"])
@login_required
def pago_editar(pago_id):
    conn = get_connection()
    try:
        if request.method == "GET":
            with conn, conn.cursor() as cur:
                cur.execute("""
                    SELECT p.id, p.pago, p.fecha_pago, NULL::text, NULL::text, c.id, c.nombre
                    FROM historial_pagos p
                    JOIN clientes c ON c.id = p.cliente_id
                    WHERE p.id=%s;
                """, (pago_id,))
                pago = cur.fetchone()

                cur.execute("SELECT id, nombre FROM clientes ORDER BY nombre;")
                clientes = cur.fetchall()

            if not pago:
                flash("Pago no encontrado.", "warning")
                return redirect(url_for('pagos_listado'))

            return render_template("editar_pago.html", pago=pago, clientes=clientes)

        # POST
        cliente_id_nuevo = int(request.form.get("cliente_id"))
        monto = request.form.get("monto")

        try:
            monto_nuevo = parse_amount(monto)
            if monto_nuevo <= 0:
                raise ValueError
        except Exception:
            flash("Monto inválido.", "warning")
            return redirect(url_for("pago_editar", pago_id=pago_id))

        with conn, conn.cursor() as cur:
            cur.execute("SELECT cliente_id, pago, fecha_pago FROM historial_pagos WHERE id=%s;", (pago_id,))
            old = cur.fetchone()
            if not old:
                flash("Pago no encontrado.", "warning")
                return redirect(url_for("pagos_listado"))

            cliente_id_old, pago_old, fecha_pago_ts = old[0], float(old[1] or 0), old[2]
            dia = fecha_pago_ts.date()

            # Validación: si cambia el cliente, que no exista pago ese día para ese cliente
            if cliente_id_nuevo != cliente_id_old:
                cur.execute("""
                    SELECT 1
                    FROM historial_pagos
                    WHERE cliente_id = %s AND fecha_pago::date = %s AND id <> %s
                    LIMIT 1;
                """, (cliente_id_nuevo, dia, pago_id))
                if cur.fetchone():
                    flash("ESTE CLIENTE YA PAGO HOY", "warning")
                    return redirect(url_for("pagos_listado", cliente_id=cliente_id_nuevo))

            # Update
            cur.execute("""
                UPDATE historial_pagos
                SET cliente_id=%s, pago=%s
                WHERE id=%s;
            """, (cliente_id_nuevo, monto_nuevo, pago_id))

            # Recalcular deudas exactas
            recalc_deuda(conn, int(cliente_id_old))
            recalc_deuda(conn, int(cliente_id_nuevo))

        flash("Pago actualizado.", "success")
        return redirect(url_for("pagos_listado", cliente_id=cliente_id_nuevo))
    finally:
        conn.close()


@app.route("/pagos/<int:pago_id>/eliminar", methods=["POST"])
@login_required
def pago_eliminar(pago_id):
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT cliente_id FROM historial_pagos WHERE id=%s;", (pago_id,))
            row = cur.fetchone()
            if not row:
                flash("Pago no encontrado.", "warning")
                return redirect(url_for("pagos_listado"))

            cliente_id = int(row[0])

            cur.execute("DELETE FROM historial_pagos WHERE id=%s;", (pago_id,))

            recalc_deuda(conn, cliente_id)

        flash("Pago eliminado.", "success")
        return redirect(url_for("pagos_listado", cliente_id=cliente_id))
    finally:
        conn.close()


# -------- Efectivo (caja diaria) --------
@app.route("/efectivo", methods=["GET", "POST"])
@login_required
def efectivo():
    if request.method == "POST":
        try:
            monto_txt = (request.form.get("monto") or "").strip()
            fecha_str = (request.form.get("fecha") or "").strip()

            if monto_txt == "":
                monto = Decimal("0.00")
            else:
                try:
                    monto = Decimal(monto_txt)
                except InvalidOperation:
                    normalizado = _parse_amount_relajado(monto_txt)
                    monto = Decimal(normalizado) if normalizado else Decimal("0.00")

            if monto < 0:
                flash("El monto de efectivo no puede ser negativo.", "warning")
                return redirect(url_for("efectivo"))

            monto = monto.quantize(Decimal("0.01"))

            try:
                f = date.fromisoformat(fecha_str) if fecha_str else today_local()
            except Exception:
                flash("Fecha inválida (usa AAAA-MM-DD).", "warning")
                return redirect(url_for("efectivo"))

            with get_connection() as conn, conn.cursor() as cur:
                cur.execute("UPDATE efectivo_diario SET monto = %s WHERE fecha = %s;", (monto, f))
                if cur.rowcount == 0:
                    cur.execute("INSERT INTO efectivo_diario (fecha, monto) VALUES (%s, %s);", (f, monto))
                conn.commit()

            flash("Efectivo guardado.", "success")
            return redirect(url_for("efectivo"))

        except Exception as e:
            print("ERROR /efectivo POST:", repr(e))
            flash(f"Error al guardar efectivo: {e}", "warning")
            return redirect(url_for("efectivo"))

    with get_connection() as conn, conn.cursor() as cur:
        hoy = today_local()
        cur.execute("SELECT COALESCE(SUM(monto),0) FROM efectivo_diario WHERE fecha = %s;", (hoy,))
        efectivo_hoy = float(cur.fetchone()[0] or 0)

        cur.execute("""
            SELECT fecha, SUM(monto) AS monto
            FROM efectivo_diario
            GROUP BY fecha
            ORDER BY fecha DESC
            LIMIT 14;
        """)
        historico = cur.fetchall()

    return render_template("efectivo.html", efectivo_hoy=efectivo_hoy, historico=historico)


# -------- Recaudo diario --------
@app.get("/pagos/diario")
@login_required
def pagos_diario():
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                SELECT fecha_pago::date AS fecha,
                       COUNT(*) AS n_pagos,
                       COALESCE(SUM(pago),0) AS total
                FROM historial_pagos
                GROUP BY fecha
                ORDER BY fecha DESC
                LIMIT 60;
            """)
            filas = cur.fetchall()
        return render_template("pagos_diario.html", filas=filas, money=money)
    finally:
        conn.close()


# -------- Clientes que NO pagaron --------
@app.get("/pagos/faltantes")
@login_required
def pagos_faltantes():
    fecha_str = (request.args.get("fecha") or "").strip()
    try:
        f = date.fromisoformat(fecha_str) if fecha_str else today_local()
    except Exception:
        flash("Fecha inválida (usa AAAA-MM-DD).", "warning")
        return redirect(url_for("pagos_faltantes"))

    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                SELECT c.id, c.nombre, COALESCE(c.deuda,0)
                FROM clientes c
                WHERE NOT EXISTS (
                    SELECT 1 FROM historial_pagos p
                    WHERE p.cliente_id = c.id AND p.fecha_pago::date = %s
                )
                ORDER BY c.nombre ASC;
            """, (f,))
            faltantes = cur.fetchall()

            cur.execute("SELECT COUNT(*) FROM clientes;")
            total_activos = cur.fetchone()[0]

        html = """
<!doctype html>
<html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Faltantes</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head><body class="bg-light">
<div class="container mt-3">
  <div class="d-flex justify-content-between align-items-center">
    <h3>Clientes SIN pago en {{ f }}</h3>
    <a class="btn btn-outline-secondary btn-sm" href="{{ url_for('pagos_listado') }}">Volver a Pagos</a>
  </div>
  <form method="get" class="mb-3">
    <label class="me-2">Fecha:</label>
    <input type="date" name="fecha" value="{{ f }}">
    <button class="btn btn-primary btn-sm ms-2" type="submit">Filtrar</button>
  </form>
  <p>Total clientes: {{ total_activos }} | Faltantes: <strong>{{ faltantes|length }}</strong></p>
  <div class="table-responsive">
    <table class="table table-sm table-striped align-middle">
      <thead><tr><th>ID</th><th>Nombre</th><th>Deuda actual</th></tr></thead>
      <tbody>
      {% for x in faltantes %}
        <tr><td>{{ x[0] }}</td><td>{{ x[1] }}</td><td>{{ money(x[2]) }}</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
</div>
</body></html>
"""
        return render_template_string(
            html, f=f.isoformat(), faltantes=faltantes,
            total_activos=total_activos, money=money
        )
    finally:
        conn.close()


# ======================= Gastos =======================
@app.route("/gastos", methods=["GET", "POST"])
@login_required
def gastos():
    if request.method == "POST":
        concepto = (request.form.get("concepto") or "").strip()
        monto_raw = (request.form.get("monto") or "").strip()
        fecha_str = (request.form.get("fecha") or "").strip()
        nota = (request.form.get("nota") or "").strip()

        if not concepto or not monto_raw:
            flash("Concepto y monto son obligatorios.", "warning")
            return redirect(url_for("gastos"))

        try:
            normalizado = _parse_amount_relajado(monto_raw) or monto_raw
            monto = Decimal(normalizado)
            if monto < 0:
                raise InvalidOperation
            monto = monto.quantize(Decimal("0.01"))
        except Exception:
            flash("Monto inválido.", "warning")
            return redirect(url_for("gastos"))

        try:
            f = date.fromisoformat(fecha_str) if fecha_str else today_local()
        except Exception:
            flash("Fecha inválida (usa AAAA-MM-DD).", "warning")
            return redirect(url_for("gastos"))

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO gastos (concepto, monto, fecha, nota)
                VALUES (%s, %s, %s, %s);
            """, (concepto, monto, f, nota))
            conn.commit()

        flash("Gasto registrado.", "success")
        return redirect(url_for("gastos"))

    desde_str = (request.args.get("desde") or "").strip()
    hasta_str = (request.args.get("hasta") or "").strip()

    where = []
    params = []
    if desde_str:
        try:
            d = date.fromisoformat(desde_str); where.append("fecha >= %s"); params.append(d)
        except Exception:
            pass
    if hasta_str:
        try:
            h = date.fromisoformat(hasta_str); where.append("fecha <= %s"); params.append(h)
        except Exception:
            pass

    sql_list = f"""
        SELECT id, fecha, concepto, monto, COALESCE(nota,'')
        FROM gastos
        {'WHERE ' + ' AND '.join(where) if where else ''}
        ORDER BY fecha DESC, id DESC
        LIMIT 200;
    """
    sql_sum = f"""
        SELECT COALESCE(SUM(monto),0)
        FROM gastos
        {'WHERE ' + ' AND '.join(where) if where else ''};
    """

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql_list, tuple(params))
        filas = cur.fetchall()

        cur.execute(sql_sum, tuple(params))
        total_filtro = float(cur.fetchone()[0] or 0)

        ini_mes = today_local().replace(day=1)
        cur.execute("SELECT COALESCE(SUM(monto),0) FROM gastos WHERE fecha >= %s;", (ini_mes,))
        total_mes = float(cur.fetchone()[0] or 0)

    return render_template(
        "gastos.html",
        filas=filas,
        total_mes=total_mes,
        total_filtro=total_filtro,
        desde=desde_str, hasta=hasta_str,
        today=today_local().isoformat(),
        money=money
    )

@app.post("/gastos/<int:gasto_id>/eliminar")
@login_required
def gasto_eliminar(gasto_id):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM gastos WHERE id=%s;", (gasto_id,))
        conn.commit()
    flash("Gasto eliminado.", "success")
    return redirect(url_for("gastos"))


# -------- Debug TZ (opcional) --------
@app.get("/tzdebug")
def tzdebug():
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SHOW TIME ZONE;")
            db_tz = cur.fetchone()[0]
            cur.execute("SELECT CURRENT_DATE, NOW(), (NOW() AT TIME ZONE 'America/Bogota');")
            cd, now_db, now_co = cur.fetchone()
        return {
            "python_today_local": today_local().isoformat(),
            "APP_TZ": str(APP_TZ),
            "db_timezone": db_tz,
            "db_current_date": cd.isoformat(),
            "db_now": str(now_db),
            "db_now_at_CO": str(now_co)
        }
    except Exception as e:
        return {"error": str(e)}, 500
        @app.get("/crecimiento")
@login_required
def crecimiento():
    """
    Version compatible con tu esquema viejo:
    Total(fecha) = SUM(deuda) + efectivo_diario(fecha)
    NOTA: deuda en clientes ya es "saldo actual", no "as-of" histórico.
    """
    ini_str = (request.args.get("inicio") or "").strip()
    fin_str = (request.args.get("fin") or "").strip()
    modo = (request.args.get("modo") or "ultimo").strip().lower()

    today = today_local()
    if not ini_str:
        ini = today.replace(day=1)
    else:
        try:
            ini = date.fromisoformat(ini_str)
        except Exception:
            flash("Fecha de inicio inválida (AAAA-MM-DD).", "warning")
            return redirect(url_for("crecimiento"))

    if not fin_str:
        fin = today
    else:
        try:
            fin = date.fromisoformat(fin_str)
        except Exception:
            flash("Fecha de fin inválida (AAAA-MM-DD).", "warning")
            return redirect(url_for("crecimiento"))

    if fin < ini:
        flash("Fin no puede ser menor que inicio.", "warning")
        return redirect(url_for("crecimiento", inicio=ini.isoformat(), fin=fin.isoformat(), modo=modo))

    def total_en(fecha_obj: date):
        with get_connection() as conn, conn.cursor() as cur:
            # Como deuda es saldo actual, la "deuda_as_of" histórica real no existe en este esquema.
            # Usamos el saldo actual como aproximación para que la pantalla funcione.
            cur.execute("SELECT COALESCE(SUM(deuda),0) FROM clientes;")
            deuda_total = float(cur.fetchone()[0] or 0)

            cur.execute("SELECT COALESCE(SUM(monto),0) FROM efectivo_diario WHERE fecha = %s;", (fecha_obj,))
            efectivo_dia = float(cur.fetchone()[0] or 0)

        return deuda_total + efectivo_dia, deuda_total, efectivo_dia

    if modo in ("ultimo", "rango"):
        if modo == "rango":
            base_fecha = ini
            comp_fecha = fin
        else:
            base_fecha = fin - timedelta(days=1)
            comp_fecha = fin

        total_base, deuda_base, efec_base = total_en(base_fecha)
        total_comp, deuda_comp, efec_comp = total_en(comp_fecha)

        delta_abs = total_comp - total_base
        crecimiento_pct = None if total_base == 0 else ((total_comp - total_base) / total_base) * 100.0

        return render_template(
            "crecimiento.html",
            ini=ini.isoformat(), fin=fin.isoformat(),
            modo=modo,
            base_fecha=base_fecha.isoformat(), comp_fecha=comp_fecha.isoformat(),
            deuda_base=deuda_base, efec_base=efec_base, total_base=total_base,
            deuda_comp=deuda_comp, efec_comp=efec_comp, total_comp=total_comp,
            delta_abs=delta_abs, crecimiento_pct=crecimiento_pct,
            money=money
        )

    # modo mensual (serie)
    snaps = []
    cursor = ini.replace(day=1)
    while cursor <= fin:
        snap = end_of_month(cursor)
        if snap > fin:
            snap = fin
        if snap >= ini:
            snaps.append(snap)
        cursor = date(cursor.year + (1 if cursor.month == 12 else 0), 1 if cursor.month == 12 else cursor.month + 1, 1)

    serie = []
    for s in snaps:
        tot, deu, ef = total_en(s)
        serie.append({"fecha": s, "total": tot, "deuda": deu, "efectivo": ef})

    for i in range(len(serie)):
        if i == 0:
            serie[i]["delta_abs"] = None
            serie[i]["delta_pct"] = None
        else:
            prev = serie[i-1]["total"]; cur = serie[i]["total"]
            serie[i]["delta_abs"] = cur - prev
            serie[i]["delta_pct"] = (None if prev == 0 else ((cur - prev) / prev) * 100.0)

    return render_template(
        "crecimiento_mensual.html",
        ini=ini.isoformat(), fin=fin.isoformat(),
        serie=serie, money=money
    )


# -------- Main --------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
