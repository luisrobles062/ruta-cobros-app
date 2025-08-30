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
    """Fecha local según APP_TZ (America/Bogota por defecto)."""
    return datetime.now(APP_TZ).date()

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

# ========= Conexión a Neon =========
RAW_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    # DSN válido SIN channel_binding y SIN comillas
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
    # Fijar TZ de la sesión en Postgres para evitar desfases si se usa CURRENT_DATE/NOW()
    with conn.cursor() as cur:
        cur.execute("SET TIME ZONE %s;", (os.getenv("DB_TZ", "America/Bogota"),))
    return conn

# ========= Utils =========
def parse_amount(txt: str) -> float:
    """
    Convierte '1.234,56', '1,234.56', '$ 1 234,56', '1234.56' -> float.
    Lanza excepción si no es número.
    """
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
    """Último día del mes de d."""
    last = calendar.monthrange(d.year, d.month)[1]
    return d.replace(day=last)

# ========= Migración / Esquema (robusta) =========
MIGRATION_SQL = r"""
-- === BASE: asegura tablas ===
CREATE TABLE IF NOT EXISTS clientes (
  id SERIAL PRIMARY KEY,
  nombre TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pagos (
  id SERIAL PRIMARY KEY,
  cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
  monto NUMERIC(14,2) NOT NULL,
  fecha_pago DATE NOT NULL DEFAULT CURRENT_DATE,
  metodo TEXT,
  nota TEXT
);

-- 1) QUITA TRIGGERS antes de alterar columnas
DROP TRIGGER IF EXISTS trg_clientes_aiu ON clientes;
DROP TRIGGER IF EXISTS trg_pagos_aiud   ON pagos;

-- 2) Renombres por esquemas viejos
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='clientes' AND column_name='monto') THEN
    EXECUTE 'ALTER TABLE clientes RENAME COLUMN monto TO monto_prestado';
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='clientes' AND column_name='deuda') THEN
    EXECUTE 'ALTER TABLE clientes RENAME COLUMN deuda TO deuda_actual';
  END IF;
END$$;

-- 3) Añade columnas del modelo actual
ALTER TABLE clientes
  ADD COLUMN IF NOT EXISTS monto_prestado NUMERIC(12,2) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS deuda_actual  NUMERIC(12,2) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS observaciones TEXT,
  ADD COLUMN IF NOT EXISTS fecha_prestamo DATE NOT NULL DEFAULT CURRENT_DATE,
  ADD COLUMN IF NOT EXISTS fecha_ultimo_pago DATE;

-- (NUEVO) Columna de archivado para esconder clientes pagados
ALTER TABLE clientes
  ADD COLUMN IF NOT EXISTS archivado BOOLEAN NOT NULL DEFAULT FALSE;

-- 4) Tipos/constraints correctos
ALTER TABLE clientes
  ALTER COLUMN monto_prestado TYPE NUMERIC(12,2) USING monto_prestado::numeric,
  ALTER COLUMN deuda_actual   TYPE NUMERIC(12,2) USING deuda_actual::numeric,
  ALTER COLUMN monto_prestado SET NOT NULL,
  ALTER COLUMN deuda_actual   SET NOT NULL,
  ALTER COLUMN monto_prestado SET DEFAULT 0,
  ALTER COLUMN deuda_actual   SET DEFAULT 0;

-- 5) Limpia columnas que ya no quieres
ALTER TABLE clientes
  DROP COLUMN IF EXISTS telefono,
  DROP COLUMN IF EXISTS documento,
  DROP COLUMN IF EXISTS fecha_registro;

-- 6) Caja diaria (sin PK para ser compatible con tablas existentes)
CREATE TABLE IF NOT EXISTS efectivo_diario (
  fecha DATE,
  monto NUMERIC(14,2) NOT NULL DEFAULT 0
);

-- 7) Funciones y triggers de recálculo
CREATE OR REPLACE FUNCTION recalc_deuda_fn(p_cid int)
RETURNS void AS $$
DECLARE
  v_total NUMERIC(14,2);
  v_prestado NUMERIC(14,2);
  v_nueva NUMERIC(14,2);
BEGIN
  SELECT COALESCE(SUM(monto),0) INTO v_total FROM pagos WHERE cliente_id = p_cid;
  SELECT monto_prestado INTO v_prestado FROM clientes WHERE id = p_cid;
  v_nueva := GREATEST(0, v_prestado - v_total);

  UPDATE clientes
  SET deuda_actual = v_nueva,
      archivado   = (v_nueva <= 0)
  WHERE id = p_cid;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION set_ultimo_pago_fn(p_cid int)
RETURNS void AS $$
BEGIN
  UPDATE clientes c
  SET fecha_ultimo_pago = (
      SELECT MAX(fecha_pago) FROM pagos WHERE cliente_id = p_cid
  )
  WHERE c.id = p_cid;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION trg_clientes_recalc()
RETURNS trigger AS $$
BEGIN
  PERFORM recalc_deuda_fn(NEW.id);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_clientes_aiu
AFTER INSERT OR UPDATE OF monto_prestado ON clientes
FOR EACH ROW EXECUTE FUNCTION trg_clientes_recalc();

CREATE OR REPLACE FUNCTION trg_pagos_recalc()
RETURNS trigger AS $$
BEGIN
  IF (TG_OP = 'INSERT') THEN
    PERFORM recalc_deuda_fn(NEW.cliente_id);
    PERFORM set_ultimo_pago_fn(NEW.cliente_id);
    RETURN NEW;
  ELSIF (TG_OP = 'UPDATE') THEN
    IF (NEW.cliente_id <> OLD.cliente_id) THEN
      PERFORM recalc_deuda_fn(OLD.cliente_id);
      PERFORM set_ultimo_pago_fn(OLD.cliente_id);
      PERFORM recalc_deuda_fn(NEW.cliente_id);
      PERFORM set_ultimo_pago_fn(NEW.cliente_id);
    ELSE
      PERFORM recalc_deuda_fn(NEW.cliente_id);
      PERFORM set_ultimo_pago_fn(NEW.cliente_id);
    END IF;
    RETURN NEW;
  ELSIF (TG_OP = 'DELETE') THEN
    PERFORM recalc_deuda_fn(OLD.cliente_id);
    PERFORM set_ultimo_pago_fn(OLD.cliente_id);
    RETURN OLD;
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_pagos_aiud
AFTER INSERT OR UPDATE OR DELETE ON pagos
FOR EACH ROW EXECUTE FUNCTION trg_pagos_recalc();

-- 8) Backfill de fechas y deudas existentes
UPDATE clientes c
SET fecha_ultimo_pago = sub.max_pago
FROM (
  SELECT cliente_id, MAX(fecha_pago) AS max_pago
  FROM pagos GROUP BY cliente_id
) sub
WHERE c.id = sub.cliente_id;

UPDATE clientes c
SET deuda_actual = c.monto_prestado
WHERE NOT EXISTS (SELECT 1 FROM pagos p WHERE p.cliente_id = c.id);

UPDATE clientes c
SET deuda_actual = GREATEST(0, c.monto_prestado - p.total)
FROM (
  SELECT cliente_id, COALESCE(SUM(monto),0) AS total
  FROM pagos GROUP BY cliente_id
) p
WHERE c.id = p.cliente_id;

-- Backfill de archivado según deuda_actual
UPDATE clientes SET archivado = (deuda_actual <= 0);

-- (NUEVO) Índice único: un pago por cliente por día
CREATE UNIQUE INDEX IF NOT EXISTS ux_pagos_cliente_fecha
ON pagos (cliente_id, fecha_pago);

-- 9) Gastos operativos (independientes de cobros)
CREATE TABLE IF NOT EXISTS gastos (
  id SERIAL PRIMARY KEY,
  concepto TEXT NOT NULL,
  monto NUMERIC(14,2) NOT NULL CHECK (monto >= 0),
  fecha DATE NOT NULL DEFAULT CURRENT_DATE,
  nota TEXT
);
CREATE INDEX IF NOT EXISTS idx_gastos_fecha ON gastos(fecha);
"""

def init_schema():
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(MIGRATION_SQL)
    finally:
        conn.close()

# Ejecuta migración al importar (sirve con gunicorn)
try:
    init_schema()
except Exception as e:
    print("WARN init schema:", e)

# ========= Totales visibles en el navbar =========
@app.context_processor
def inject_totales():
    deuda_total = 0.0
    efectivo_hoy = 0.0
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT COALESCE(SUM(deuda_actual),0) FROM clientes;")
            deuda_total = float(cur.fetchone()[0] or 0)
            hoy = today_local()
            cur.execute("SELECT COALESCE(SUM(monto),0) FROM efectivo_diario WHERE fecha = %s;", (hoy,))
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

# Home: listado de clientes morosos (solo con deuda > 0 y no archivados)
@app.route("/")
@login_required
def home():
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                SELECT id, nombre, monto_prestado, deuda_actual, COALESCE(observaciones,'') AS obs,
                       fecha_prestamo, fecha_ultimo_pago
                FROM clientes
                WHERE archivado = FALSE AND deuda_actual > 0
                ORDER BY id DESC;
            """)
            clientes = cur.fetchall()

            cur.execute("SELECT COUNT(*) FROM clientes WHERE archivado = FALSE AND deuda_actual > 0;")
            total_clientes = cur.fetchone()[0]

            cur.execute("SELECT COALESCE(SUM(monto),0) FROM pagos;")
            total_recaudado = cur.fetchone()[0]

        return render_template(
            "inicio.html",
            clientes=clientes,
            total_clientes=total_clientes,
            total_recaudado=money(total_recaudado),
        )
    finally:
        conn.close()

# -------- Clientes (archivados/pagados) --------
@app.get("/clientes/archivados")
@login_required
def clientes_archivados():
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                SELECT id, nombre, monto_prestado, deuda_actual, fecha_prestamo, fecha_ultimo_pago
                FROM clientes
                WHERE archivado = TRUE OR deuda_actual = 0
                ORDER BY id DESC;
            """)
            filas = cur.fetchall()
        return render_template("clientes_archivados.html", filas=filas, money=money)
    finally:
        conn.close()

@app.post("/clientes/<int:cliente_id>/eliminar_def")
@login_required
def cliente_eliminar_def(cliente_id):
    # CUIDADO: borra cliente y sus pagos (ON DELETE CASCADE)
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
                INSERT INTO clientes (nombre, monto_prestado, deuda_actual, observaciones, fecha_prestamo)
                VALUES (%s, %s, %s, %s, %s);
            """, (nombre, monto, monto, observaciones, fecha_prestamo))
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
                    SELECT id, nombre, monto_prestado, deuda_actual, COALESCE(observaciones,''),
                           fecha_prestamo, fecha_ultimo_pago
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
                SET nombre=%s, monto_prestado=%s, observaciones=%s, fecha_prestamo=%s
                WHERE id=%s;
            """, (nombre, monto, observaciones, fecha_prestamo, cliente_id))
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
            # Listado de clientes activos (no archivados) para el <select>
            cur.execute("SELECT id, nombre FROM clientes WHERE archivado = FALSE ORDER BY nombre;")
            clientes = cur.fetchall()

            if cliente_id_filtro:
                cur.execute("""
                    SELECT p.id, p.monto, p.fecha_pago, p.metodo, p.nota,
                           c.id AS cliente_id, c.nombre
                    FROM pagos p
                    JOIN clientes c ON c.id = p.cliente_id
                    WHERE p.cliente_id = %s
                    ORDER BY p.fecha_pago DESC, p.id DESC;
                """, (cliente_id_filtro,))
                pagos = cur.fetchall()

                cur.execute("""
                    SELECT id, nombre, monto_prestado, deuda_actual,
                           fecha_prestamo, fecha_ultimo_pago
                    FROM clientes
                    WHERE id = %s;
                """, (cliente_id_filtro,))
                cli = cur.fetchone()
                if not cli:
                    flash("Cliente no encontrado.", "warning")
                    return redirect(url_for("pagos_listado"))

                cur.execute("SELECT COALESCE(SUM(monto),0) FROM pagos WHERE cliente_id = %s;", (cliente_id_filtro,))
                total_pagado_cli = float(cur.fetchone()[0] or 0)

                resumen = dict(
                    id=cli[0],
                    nombre=cli[1],
                    monto_prestado=float(cli[2] or 0),
                    deuda_actual=float(cli[3] or 0),
                    fecha_prestamo=cli[4],
                    fecha_ultimo_pago=cli[5],
                    total_pagado=total_pagado_cli
                )
            else:
                cur.execute("""
                    SELECT p.id, p.monto, p.fecha_pago, p.metodo, p.nota,
                           c.id AS cliente_id, c.nombre
                    FROM pagos p
                    JOIN clientes c ON c.id = p.cliente_id
                    WHERE c.archivado = FALSE
                    ORDER BY p.fecha_pago DESC, p.id DESC;
                """)
                pagos = cur.fetchall()
                resumen = None

            cur.execute("SELECT COALESCE(SUM(monto),0) FROM pagos;")
            total_recaudado = cur.fetchone()[0]

            hoy = today_local()
            cur.execute("SELECT COALESCE(SUM(monto),0) FROM pagos WHERE fecha_pago = %s;", (hoy,))
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
    metodo = (request.form.get("metodo") or "").strip()
    nota = (request.form.get("nota") or "").strip()
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
            # ❗️VALIDACIÓN: un pago por cliente por día
            cur.execute("""
                SELECT 1
                FROM pagos
                WHERE cliente_id = %s AND fecha_pago = %s
                LIMIT 1;
            """, (int(cliente_id), fecha_pago))
            ya_pago = cur.fetchone() is not None
            if ya_pago:
                flash("ESTE CLIENTE YA PAGO HOY", "warning")
                return redirect(url_for("pagos_listado", cliente_id=cliente_id))

            cur.execute("""
                INSERT INTO pagos (cliente_id, monto, fecha_pago, metodo, nota)
                VALUES (%s, %s, %s, %s, %s);
            """, (int(cliente_id), monto_norm, fecha_pago, metodo, nota))
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
                    SELECT p.id, p.monto, p.fecha_pago, p.metodo, p.nota, c.id, c.nombre
                    FROM pagos p
                    JOIN clientes c ON c.id = p.cliente_id
                    WHERE p.id=%s;
                """, (pago_id,))
                pago = cur.fetchone()

                # Dropdown sólo con clientes activos
                cur.execute("SELECT id, nombre FROM clientes WHERE archivado = FALSE ORDER BY nombre;")
                clientes = cur.fetchall()

            if not pago:
                flash("Pago no encontrado.", "warning")
                return redirect(url_for('pagos_listado'))

            return render_template("editar_pago.html", pago=pago, clientes=clientes)

        # POST
        cliente_id = request.form.get("cliente_id")
        monto = request.form.get("monto")
        metodo = (request.form.get("metodo") or "").strip()
        nota = (request.form.get("nota") or "").strip()

        try:
            monto_norm = parse_amount(monto)
            if monto_norm <= 0:
                raise ValueError
        except Exception:
            flash("Monto inválido.", "warning")
            return redirect(url_for("pago_editar", pago_id=pago_id))

        with conn, conn.cursor() as cur:
            # Tomamos la fecha original del pago (no se edita en el form)
            cur.execute("SELECT fecha_pago FROM pagos WHERE id=%s;", (pago_id,))
            row = cur.fetchone()
            if not row:
                flash("Pago no encontrado.", "warning")
                return redirect(url_for("pagos_listado"))
            fecha_pago = row[0]

            # ❗️VALIDACIÓN: evitar duplicado al cambiar cliente
            cur.execute("""
                SELECT 1
                FROM pagos
                WHERE cliente_id = %s AND fecha_pago = %s AND id <> %s
                LIMIT 1;
            """, (int(cliente_id), fecha_pago, pago_id))
            ya_pago = cur.fetchone() is not None
            if ya_pago:
                flash("ESTE CLIENTE YA PAGO HOY", "warning")
                return redirect(url_for("pagos_listado", cliente_id=cliente_id))

            cur.execute("""
                UPDATE pagos
                SET cliente_id=%s, monto=%s, metodo=%s, nota=%s
                WHERE id=%s;
            """, (int(cliente_id), monto_norm, metodo, nota, pago_id))
        flash("Pago actualizado.", "success")
        return redirect(url_for("pagos_listado", cliente_id=cliente_id))
    finally:
        conn.close()

@app.route("/pagos/<int:pago_id>/eliminar", methods=["POST"])
@login_required
def pago_eliminar(pago_id):
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("DELETE FROM pagos WHERE id=%s;", (pago_id,))
        flash("Pago eliminado.", "success")
        return redirect(url_for("pagos_listado"))
    finally:
        conn.close()

# -------- Efectivo (caja diaria) --------
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
                    if not normalizado:
                        monto = Decimal("0.00")
                    else:
                        monto = Decimal(normalizado)

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
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS efectivo_diario (
                      fecha DATE,
                      monto NUMERIC(14,2) NOT NULL DEFAULT 0
                    );
                """)
                cur.execute("UPDATE efectivo_diario SET monto = %s WHERE fecha = %s;", (monto, f))
                if cur.rowcount == 0:
                    cur.execute("INSERT INTO efectivo_diario (fecha, monto) VALUES (%s, %s);", (f, monto))
            flash("Efectivo guardado.", "success")
            return redirect(url_for("efectivo"))

        except Exception as e:
            print("ERROR /efectivo POST:", repr(e))
            flash(f"Error al guardar efectivo: {e}", "warning")
            return redirect(url_for("efectivo"))

    with get_connection() as conn, conn.cursor() as cur:
        hoy = today_local()
        cur.execute("SELECT COALESCE(SUM(monto),0) FROM efectivo_diario WHERE fecha = %s;", (hoy,))
        row = cur.fetchone()
        efectivo_hoy = float((row[0] if row else 0) or 0)

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
                       COALESCE(SUM(monto),0) AS total
                FROM pagos
                GROUP BY fecha
                ORDER BY fecha DESC
                LIMIT 60;
            """)
            filas = cur.fetchall()
        return render_template("pagos_diario.html", filas=filas, money=money)
    finally:
        conn.close()

# -------- NUEVO: Clientes que NO pagaron (inline template) --------
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
                SELECT c.id, c.nombre, c.deuda_actual
                FROM clientes c
                WHERE c.archivado = FALSE
                  AND NOT EXISTS (
                    SELECT 1 FROM pagos p
                    WHERE p.cliente_id = c.id AND p.fecha_pago = %s
                  )
                ORDER BY c.nombre ASC;
            """, (f,))
            faltantes = cur.fetchall()

            cur.execute("SELECT COUNT(*) FROM clientes WHERE archivado = FALSE;")
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
  <p>Total activos: {{ total_activos }} | Faltantes: <strong>{{ faltantes|length }}</strong></p>
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

# ======================= NUEVO: Gastos =======================
@app.route("/gastos", methods=["GET", "POST"])
@login_required
def gastos():
    # POST: crear gasto
    if request.method == "POST":
        concepto = (request.form.get("concepto") or "").strip()
        monto_raw = (request.form.get("monto") or "").strip()
        fecha_str = (request.form.get("fecha") or "").strip()
        nota = (request.form.get("nota") or "").strip()

        if not concepto or not monto_raw:
            flash("Concepto y monto son obligatorios.", "warning")
            return redirect(url_for("gastos"))

        # Normalizamos monto con Decimal pero aceptando formatos flexibles
        try:
            normalizado = _parse_amount_relajado(monto_raw) or monto_raw
            monto = Decimal(normalizado)
            if monto < 0:
                raise InvalidOperation
            monto = monto.quantize(Decimal("0.01"))
        except Exception:
            flash("Monto inválido.", "warning")
            return redirect(url_for("gastos"))

        # Fecha
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
        flash("Gasto registrado.", "success")
        return redirect(url_for("gastos"))

    # GET: filtro opcional por fecha
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

        # Total del mes actual (rápido)
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
    flash("Gasto eliminado.", "success")
    return redirect(url_for("gastos"))

# ======================= NUEVO: Crecimiento mejorado =======================
@app.get("/crecimiento")
@login_required
def crecimiento():
    """
    modos:
      - 'ultimo' (default): Total(fin) vs Total(fin-1 día)
      - 'rango'           : Total(fin) vs Total(inicio)
      - 'mensual'         : Serie mes a mes (MoM) con snapshots reales
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
            cur.execute("""
                WITH pagos_acum AS (
                  SELECT cliente_id, COALESCE(SUM(monto),0) AS total
                  FROM pagos
                  WHERE fecha_pago <= %s
                  GROUP BY cliente_id
                )
                SELECT COALESCE(SUM(GREATEST(0, c.monto_prestado - COALESCE(p.total,0))), 0) AS deuda_as_of
                FROM clientes c
                LEFT JOIN pagos_acum p ON p.cliente_id = c.id
                WHERE c.fecha_prestamo <= %s;
            """, (fecha_obj, fecha_obj))
            deuda_as_of = float(cur.fetchone()[0] or 0)

            cur.execute("SELECT COALESCE(SUM(monto),0) FROM efectivo_diario WHERE fecha = %s;", (fecha_obj,))
            efectivo_dia = float(cur.fetchone()[0] or 0)

        return deuda_as_of + efectivo_dia, deuda_as_of, efectivo_dia

    # ===== modos 'ultimo' y 'rango' =====
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

    # ===== modo 'mensual' (MoM real) =====
    snaps = []
    cursor = ini.replace(day=1)
    while cursor <= fin:
        snap = end_of_month(cursor)
        if snap > fin:
            snap = fin
        if snap >= ini:
            snaps.append(snap)
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)

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

# -------- Main --------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
