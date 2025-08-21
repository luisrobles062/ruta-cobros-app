# app.py
# -*- coding: utf-8 -*-
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify, send_from_directory
)
import psycopg2
import psycopg2.extras
import os

app = Flask(__name__)

# ------------------ Configuración ------------------
app.secret_key = os.getenv("SECRET_KEY", "secreto")  # define SECRET_KEY en Render para producción

RAW_DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

def _sanitize_dsn(dsn: str) -> str:
    """Limpia comillas accidentales y elimina 'channel_binding' si lo pegaron desde Neon."""
    dsn = (dsn or "").strip().strip('\'"').strip()
    if not dsn:
        return dsn
    # El parámetro channel_binding rompe en psycopg2: lo quitamos si viene
    if "channel_binding=" in dsn and "?" in dsn:
        base, qs = dsn.split("?", 1)
        kvs = [p for p in qs.split("&") if not p.startswith("channel_binding=")]
        dsn = base + ("?" + "&".join(kvs) if kvs else "")
    return dsn

DATABASE_URL = _sanitize_dsn(RAW_DATABASE_URL)

def get_db_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL no está definido. Configúralo en el panel de Render.")
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.DictCursor)

# ------------------ Utilidades ------------------
def require_login():
    if "usuario" not in session:
        return False
    return True

# ------------------ Rutas auxiliares ------------------
@app.get("/health")
def health():
    return jsonify(status="ok")

@app.get("/dbcheck")
def dbcheck():
    try:
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1;")
            row = cur.fetchone()
        return jsonify(db="ok" if row and row[0] == 1 else "fail")
    except Exception as e:
        return jsonify(db="error", detail=str(e)), 500

@app.get("/favicon.ico")
def favicon():
    static_path = os.path.join(app.root_path, "static")
    ico_path = os.path.join(static_path, "favicon.ico")
    if os.path.exists(ico_path):
        return send_from_directory(static_path, "favicon.ico", mimetype="image/x-icon")
    return ("", 204)

# ------------------ Login ------------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # Soporta JSON y formulario
        data = request.get_json(silent=True) if request.is_json else request.form
        usuario = (data.get("usuario") or "").strip()
        contrasena = (data.get("contrasena") or "").strip()  # OJO: 'contrasena' sin ñ para coincidir con el form

        if not usuario or not contrasena:
            flash("Por favor, completa usuario y contraseña.")
            return render_template("login.html"), 200

        # Demo simple: admin/admin. Ajusta para usar DB si lo deseas.
        if usuario == "admin" and contrasena == "admin":
            session["usuario"] = usuario
            return redirect(url_for("inicio"))
        else:
            flash("Usuario o contraseña incorrectos")
            return render_template("login.html"), 200

    return render_template("login.html")

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ------------------ Clientes ------------------
@app.get("/inicio")
def inicio():
    if not require_login():
        return redirect(url_for("login"))
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM clientes ORDER BY id ASC;")
            clientes = cur.fetchall()
    finally:
        conn.close()
    return render_template("inicio.html", clientes=clientes)

@app.route("/nuevo", methods=["GET", "POST"])
def nuevo_cliente():
    if not require_login():
        return redirect(url_for("login"))

    if request.method == "POST":
        data = request.get_json(silent=True) if request.is_json else request.form
        nombre = (data.get("nombre") or "").strip()
        monto_raw = (data.get("monto") or "").strip()
        observaciones = (data.get("observaciones") or "").strip()

        if not nombre or not monto_raw:
            flash("Nombre y monto son obligatorios.")
            return redirect(url_for("nuevo_cliente"))
        try:
            monto = float(monto_raw)
        except ValueError:
            flash("El monto debe ser numérico.")
            return redirect(url_for("nuevo_cliente"))

        deuda = monto
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO clientes (nombre, monto_prestado, deuda_actual, observaciones)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (nombre, monto, deuda, observaciones),
                )
                conn.commit()
            flash("Cliente agregado correctamente")
        finally:
            conn.close()

        return redirect(url_for("inicio"))

    return render_template("nuevo_cliente.html")

# ------------------ Pagos ------------------
@app.post("/pago/<int:id>")
def registrar_pago(id):
    if not require_login():
        return redirect(url_for("login"))

    data = request.get_json(silent=True) if request.is_json else request.form
    monto_raw = (data.get("monto_pago") or "").strip()

    try:
        monto_pago = float(monto_raw)
        if monto_pago <= 0:
            raise ValueError
    except ValueError:
        flash("El monto de pago debe ser un número mayor que 0.")
        return redirect(url_for("inicio"))

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT deuda_actual FROM clientes WHERE id = %s", (id,))
            row = cur.fetchone()
            if not row:
                flash("Cliente no encontrado.")
                return redirect(url_for("inicio"))

            deuda_actual = float(row[0])
            nueva_deuda = max(deuda_actual - monto_pago, 0.0)

            cur.execute("UPDATE clientes SET deuda_actual = %s WHERE id = %s", (nueva_deuda, id))
            conn.commit()
            flash("Pago registrado correctamente")
    finally:
        conn.close()

    return redirect(url_for("inicio"))

# ------------------ Inicialización ------------------
def crear_tabla():
    """Crea la tabla si no existe (idempotente)."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS clientes (
                    id SERIAL PRIMARY KEY,
                    nombre VARCHAR(100) NOT NULL,
                    monto_prestado NUMERIC(12,2) NOT NULL,
                    deuda_actual NUMERIC(12,2) NOT NULL,
                    observaciones TEXT
                );
            """)
            conn.commit()
    finally:
        conn.close()

if __name__ == "__main__":
    # En Render ejecutas con: gunicorn app:app --bind 0.0.0.0:$PORT --workers 2
    # Pero si corres local, esto levanta el servidor dev:
    crear_tabla()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
