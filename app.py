# app.py
# -*- coding: utf-8 -*-
import os
from datetime import date
from urllib.parse import urlparse, parse_qsl

from flask import (
    Flask, render_template, request, redirect, url_for, flash, jsonify
)
import psycopg2

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "secreto")

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
    return psycopg2.connect(dsn)

# ========= Util ========
def parse_amount(txt: str) -> float:
    """
    Convierte '1.234,56' o '1234.56' o '1,234.56' a float con robustez.
    """
    t = (txt or "").strip().replace(" ", "")
    if "," in t and "." in t:
        # asume coma como miles → quítalas
        t = t.replace(",", "")
    elif "," in t and "." not in t:
        # asume coma como decimal
        t = t.replace(",", ".")
    return float(t)

def money(n):
    try:
        return f"${float(n):,.2f}"
    except Exception:
        return n

# ========= Migración / Esquema (modelo final + fechas + caja) =========
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

-- === 1) QUITA TRIGGERS antes de alterar tipos/columnas ===
DROP TRIGGER IF EXISTS trg_clientes_aiu ON clientes;
DROP TRIGGER IF EXISTS trg_pagos_aiud   ON pagos;

-- === 2) Renombres por esquemas viejos ===
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

-- === 3) Añade columnas del modelo actual ===
ALTER TABLE clientes
  ADD COLUMN IF NOT EXISTS monto_prestado NUMERIC(12,2) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS deuda_actual  NUMERIC(12,2) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS observaciones TEXT,
  ADD COLUMN IF NOT EXISTS fecha_prestamo DATE NOT NULL DEFAULT CURRENT_DATE,
  ADD COLUMN IF NOT EXISTS fecha_ultimo_pago DATE;

-- === 4) Tipos/constraints correctos (ya sin triggers molestando) ===
ALTER TABLE clientes
  ALTER COLUMN monto_prestado TYPE NUMERIC(12,2) USING monto_prestado::numeric,
  ALTER COLUMN deuda_actual   TYPE NUMERIC(12,2) USING deuda_actual::numeric,
  ALTER COLUMN monto_prestado SET NOT NULL,
  ALTER COLUMN deuda_actual   SET NOT NULL,
  ALTER COLUMN monto_prestado SET DEFAULT 0,
  ALTER COLUMN deuda_actual   SET DEFAULT 0;

-- === 5) Limpia columnas que ya no quieres ===
ALTER TABLE clientes
  DROP COLUMN IF EXISTS telefono,
  DROP COLUMN IF EXISTS documento,
  DROP COLUMN IF EXISTS fecha_registro;

-- === 6) Caja diaria ===
CREATE TABLE IF NOT EXISTS efectivo_diario (
  fecha DATE PRIMARY KEY,
  monto NUMERIC(14,2) NOT NULL DEFAULT 0
);

-- === 7) Funciones de recálculo y fechas ===
CREATE OR REPLACE FUNCTION recalc_deuda_fn(p_cid int)
RETURNS void AS $$
BEGIN
  UPDATE clientes c
  SET deuda_actual = GREATEST(
      0,
      c.monto_prestado - COALESCE((SELECT SUM(monto) FROM pagos WHERE cliente_id = p_cid), 0)
  )
  WHERE c.id = p_cid;
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

-- === 8) Triggers (recrear) ===
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

-- === 9) Backfill: alinear deudas y fechas existentes ===
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
            cur.execute("SELECT COALESCE(monto,0) FROM efectivo_diario WHERE fecha = CURRENT_DATE;")
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

# ========= Rutas =========

# Home: listado de clientes + totales históricos
@app.route("/")
def home():
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                SELECT id, nombre, monto_prestado, deuda_actual, COALESCE(observaciones,'') AS obs,
                       fecha_prestamo, fecha_ultimo_pago
                FROM clientes
                ORDER BY id DESC;
            """)
            clientes = cur.fetchall()

            cur.execute("SELECT COUNT(*) FROM clientes;")
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

# Login (opcional)
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")
    flash("Inicio de sesión simulado.", "info")
    return redirect(url_for("home"))

# -------- Clientes --------
@app.route("/clientes/nuevo", methods=["GET", "POST"])
def cliente_nuevo():
    if request.method == "GET":
        return render_template("nuevo.html")  # nombre, monto_prestado, observaciones, fecha_prestamo (opcional)

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
        fecha_prestamo = date.fromisoformat(fecha_str) if fecha_str else date.today()
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
            fecha_prestamo = date.fromisoformat(fecha_str) if fecha_str else date.today()
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
def pagos_listado():
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                SELECT p.id, p.monto, p.fecha_pago, p.metodo, p.nota,
                       c.id AS cliente_id, c.nombre
                FROM pagos p
                JOIN clientes c ON c.id = p.cliente_id
                ORDER BY p.fecha_pago DESC, p.id DESC;
            """)
            pagos = cur.fetchall()

            cur.execute("SELECT id, nombre FROM clientes ORDER BY nombre;")
            clientes = cur.fetchall()

            cur.execute("SELECT COALESCE(SUM(monto),0) FROM pagos;")
            total_recaudado = cur.fetchone()[0]

        return render_template(
            "pagos.html",
            pagos=pagos,
            clientes=clientes,
            total_recaudado=money(total_recaudado),
        )
    finally:
        conn.close()

@app.route("/pagos/nuevo", methods=["POST"])
def pago_nuevo():
    cliente_id = request.form.get("cliente_id")
    monto = request.form.get("monto")
    metodo = (request.form.get("metodo") or "").strip()
    nota = (request.form.get("nota") or "").strip()
    fecha_str = (request.form.get("fecha_pago") or "").strip()

    if not cliente_id or not monto:
        flash("Cliente y monto son obligatorios.", "warning")
        return redirect(url_for("pagos_listado"))

    try:
        monto_norm = parse_amount(monto)
        if monto_norm <= 0:
            raise ValueError
    except Exception:
        flash("Monto inválido.", "warning")
        return redirect(url_for("pagos_listado"))

    try:
        fecha_pago = date.fromisoformat(fecha_str) if fecha_str else date.today()
    except Exception:
        flash("Fecha de pago inválida (usa AAAA-MM-DD).", "warning")
        return redirect(url_for("pagos_listado"))

    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO pagos (cliente_id, monto, fecha_pago, metodo, nota)
                VALUES (%s, %s, %s, %s, %s);
            """, (int(cliente_id), monto_norm, fecha_pago, metodo, nota))
        flash("Pago registrado.", "success")
        return redirect(url_for("pagos_listado"))
    finally:
        conn.close()

@app.route("/pagos/<int:pago_id>/editar", methods=["GET", "POST"])
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

                cur.execute("SELECT id, nombre FROM clientes ORDER BY nombre;")
                clientes = cur.fetchall()

            if not pago:
                flash("Pago no encontrado.", "warning")
                return redirect(url_for("pagos_listado"))

            return render_template("editar_pago.html", pago=pago, clientes=clientes)

        cliente_id = request.form.get("cliente_id")
        monto = request.form.get("monto")
        metodo = (request.form.get("metodo") or "").strip()
        nota = (request.form.get("nota") or "").strip()

        try:
            monto_norm = parse_amount(monto)
        except Exception:
            flash("Monto inválido.", "warning")
            return redirect(url_for("pago_editar", pago_id=pago_id))

        with conn, conn.cursor() as cur:
            cur.execute("""
                UPDATE pagos
                SET cliente_id=%s, monto=%s, metodo=%s, nota=%s
                WHERE id=%s;
            """, (int(cliente_id), monto_norm, metodo, nota, pago_id))
        flash("Pago actualizado.", "success")
        return redirect(url_for("pagos_listado"))
    finally:
        conn.close()

@app.route("/pagos/<int:pago_id>/eliminar", methods=["POST"])
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
# --- pega esto reemplazando toda tu función efectivo() ---
from decimal import Decimal, InvalidOperation

def _parse_amount_relajado(txt: str):
    """
    123,45  -> 123.45
    1.234,56 -> 1234.56
    1,234.56 -> 1234.56
    "" -> None
    """
    if txt is None:
        return None
    t = txt.strip()
    if not t:
        return None
    # quita separadores comunes y símbolos
    for ch in ["$", "€", "₡", "₲", "₵", "£", "¥", "₿", " "]:
        t = t.replace(ch, "")
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            # coma decimal
            t = t.replace(".", "").replace(",", ".")
        else:
            # punto decimal
            t = t.replace(",", "")
    elif "," in t and "." not in t:
        t = t.replace(",", ".")
    return t

@app.route("/efectivo", methods=["GET", "POST"])
def efectivo():
    if request.method == "POST":
        try:
            monto_txt = (request.form.get("monto") or "").strip()
            fecha_str = (request.form.get("fecha") or "").strip()

            # 1) Parseo robusto del monto
            if monto_txt == "":
                monto = Decimal("0.00")
            else:
                try:
                    # primero intenta estilo "normal" 123 o 123.45
                    monto = Decimal(monto_txt)
                except InvalidOperation:
                    # intenta el parser relajado (coma, miles, etc.)
                    normalizado = _parse_amount_relajado(monto_txt)
                    if not normalizado:
                        monto = Decimal("0.00")
                    else:
                        monto = Decimal(normalizado)

            if monto < 0:
                flash("El monto de efectivo no puede ser negativo.", "warning")
                return redirect(url_for("efectivo"))

            # Redondea a 2 decimales
            monto = monto.quantize(Decimal("0.01"))

            # 2) Fecha: si viene vacía, usa hoy
            try:
                f = date.fromisoformat(fecha_str) if fecha_str else date.today()
            except Exception:
                flash("Fecha inválida (usa AAAA-MM-DD).", "warning")
                return redirect(url_for("efectivo"))

            # 3) DB: asegura tabla y guarda (sin ON CONFLICT)
with get_connection() as conn, conn.cursor() as cur:
    # Si la tabla ya existe sin PK, esto no la rompe ni la altera.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS efectivo_diario (
          fecha DATE,
          monto NUMERIC(14,2) NOT NULL DEFAULT 0
        );
    """)
    # Intentamos actualizar primero
    cur.execute("UPDATE efectivo_diario SET monto = %s WHERE fecha = %s;", (monto, f))
    if cur.rowcount == 0:
        # Si no había fila para esa fecha, insertamos
        cur.execute("INSERT INTO efectivo_diario (fecha, monto) VALUES (%s, %s);", (f, monto))

flash("Efectivo guardado.", "success")
return redirect(url_for("efectivo"))

    # GET (sin cambios mayores)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT COALESCE(monto,0) FROM efectivo_diario WHERE fecha=CURRENT_DATE;")
        row = cur.fetchone()
        efectivo_hoy = float((row[0] if row else 0) or 0)
        cur.execute("""
            SELECT fecha, monto FROM efectivo_diario
            ORDER BY fecha DESC
            LIMIT 14;
        """)
        historico = cur.fetchall()
    return render_template("efectivo.html", efectivo_hoy=efectivo_hoy, historico=historico)

# -------- Main --------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
