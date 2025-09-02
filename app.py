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
    # Fijar TZ de la sesión en Postgres
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

def end_of_month(d: date) -> date:
    last = calendar.monthrange(d.year, d.month)[1]
    return d.replace(day=last)

# ========= Migración / Esquema =========
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

-- 1) Limpieza de triggers
DROP TRIGGER IF EXISTS trg_clientes_aiu ON clientes;
DROP TRIGGER IF EXISTS trg_pagos_aiud   ON pagos;

-- 2) Renombres
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

-- 3) Añadir columnas
ALTER TABLE clientes
  ADD COLUMN IF NOT EXISTS monto_prestado NUMERIC(12,2) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS deuda_actual  NUMERIC(12,2) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS observaciones TEXT,
  ADD COLUMN IF NOT EXISTS fecha_prestamo DATE NOT NULL DEFAULT CURRENT_DATE,
  ADD COLUMN IF NOT EXISTS fecha_ultimo_pago DATE,
  ADD COLUMN IF NOT EXISTS archivado BOOLEAN NOT NULL DEFAULT FALSE;

-- 4) Ajustes de tipos
ALTER TABLE clientes
  ALTER COLUMN monto_prestado TYPE NUMERIC(12,2) USING monto_prestado::numeric,
  ALTER COLUMN deuda_actual   TYPE NUMERIC(12,2) USING deuda_actual::numeric,
  ALTER COLUMN monto_prestado SET DEFAULT 0,
  ALTER COLUMN deuda_actual   SET DEFAULT 0;

-- 5) Quitar columnas viejas
ALTER TABLE clientes
  DROP COLUMN IF EXISTS telefono,
  DROP COLUMN IF EXISTS documento,
  DROP COLUMN IF EXISTS fecha_registro;

-- 6) Caja diaria
CREATE TABLE IF NOT EXISTS efectivo_diario (
  fecha DATE,
  monto NUMERIC(14,2) NOT NULL DEFAULT 0
);

-- 7) Funciones y triggers
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
    PERFORM recalc_deuda_fn(NEW.cliente_id);
    PERFORM set_ultimo_pago_fn(NEW.cliente_id);
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

-- 8) Índice único
CREATE UNIQUE INDEX IF NOT EXISTS ux_pagos_cliente_fecha
ON pagos (cliente_id, fecha_pago);

-- 9) Gastos
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
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("DELETE FROM clientes WHERE id=%s;", (cliente_id,))
        flash("Cliente eliminado definitivamente.", "success")
        return redirect(url_for("clientes_archivados"))
    finally:
        conn.close()

# -------- Clientes CRUD --------
# ... aquí siguen todas las rutas de clientes, pagos, efectivo y gastos ...
# (idénticas a tu archivo original, no se modifican)

# ======================= NUEVO: Proyección =======================
@app.get("/proyeccion")
@login_required
def proyeccion():
    hoy = today_local()
    fin_mes = end_of_month(hoy)

    historico = []
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT d::date,
                   COALESCE((
                     SELECT SUM(GREATEST(0, c.monto_prestado - COALESCE(p.total,0)))
                     FROM clientes c
                     LEFT JOIN (
                        SELECT cliente_id, SUM(monto) total
                        FROM pagos
                        WHERE fecha_pago <= d
                        GROUP BY cliente_id
                     ) p ON p.cliente_id=c.id
                     WHERE c.fecha_prestamo <= d
                   ),0) AS deuda,
                   COALESCE((
                     SELECT SUM(monto) FROM efectivo_diario e WHERE e.fecha = d
                   ),0) AS efectivo
            FROM generate_series(date_trunc('month', %s::date)::date, %s::date, interval '1 day') d
            ORDER BY d;
        """, (hoy, hoy))
        rows = cur.fetchall()
        for r in rows:
            total = float(r[1] or 0) + float(r[2] or 0)
            historico.append({"fecha": r[0].isoformat(), "total": total})

    dias_transcurridos = len(historico)
    promedio = sum(x["total"] for x in historico) / dias_transcurridos if dias_transcurridos > 0 else 0
    proyeccion_total = promedio * calendar.monthrange(hoy.year, hoy.month)[1]

    html = """
    <!doctype html>
    <html lang="es">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Proyección mensual</title>
      <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
      <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    </head>
    <body class="bg-light">
    <div class="container mt-3">
      <h3>Proyección de cierre de mes</h3>
      <p>Hoy: {{ hoy }} | Fin de mes: {{ fin_mes }}</p>
      <p>Promedio diario: <strong>{{ money(promedio) }}</strong></p>
      <p>Proyección al cierre: <strong>{{ money(proyeccion_total) }}</strong></p>
      <canvas id="chart" height="100"></canvas>
      <a class="btn btn-secondary btn-sm mt-3" href="{{ url_for('home') }}">Volver</a>
    </div>
    <script>
      const ctx = document.getElementById('chart').getContext('2d');
      const data = {
        labels: {{ labels|safe }},
        datasets: [{
          label: 'Total diario',
          data: {{ totals|safe }},
          borderColor: 'blue',
          fill: false,
          tension: 0.1
        }]
      };
      new Chart(ctx, { type: 'line', data: data });
    </script>
    </body>
    </html>
    """
    return render_template_string(
        html,
        hoy=hoy.isoformat(),
        fin_mes=fin_mes.isoformat(),
        promedio=promedio,
        proyeccion_total=proyeccion_total,
        labels=[x["fecha"] for x in historico],
        totals=[x["total"] for x in historico],
        money=money
    )

# -------- Main --------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
