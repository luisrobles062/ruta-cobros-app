import os
from pathlib import Path
from datetime import date
from urllib.parse import urlparse, parse_qsl

from flask import (
    Flask, render_template, request, redirect, url_for, flash
)
import psycopg2

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "secreto")

# ========= Conexión a Neon =========
# 1) Usa DATABASE_URL (Render/entorno)
# 2) Si no está, usa TU URL de Neon (la que compartiste)
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://neondb_owner:npg_DqyQpk4iBLh3@ep-still-water-adszkvnv-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
)

def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL no configurada.")
    url = urlparse(DATABASE_URL)
    params = dict(parse_qsl(url.query))
    # psycopg2 no usa channel_binding
    params.pop("channel_binding", None)

    dsn_parts = [
        f"dbname={url.path.lstrip('/')}",
        f"user={url.username}",
        f"password={url.password}",
        f"host={url.hostname}",
        f"port={url.port or 5432}",
        "sslmode=require",
    ]
    dsn = " ".join(dsn_parts)
    return psycopg2.connect(dsn)

# ========= Esquema =========
DDL = """
CREATE TABLE IF NOT EXISTS clientes (
    id SERIAL PRIMARY KEY,
    nombre TEXT NOT NULL,
    telefono TEXT,
    documento TEXT,
    fecha_registro DATE DEFAULT CURRENT_DATE
);

CREATE TABLE IF NOT EXISTS pagos (
    id SERIAL PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    monto NUMERIC(14,2) NOT NULL,
    fecha_pago DATE NOT NULL DEFAULT CURRENT_DATE,
    metodo TEXT,
    nota TEXT
);
"""

def init_schema():
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(DDL)
    finally:
        conn.close()

@app.before_first_request
def _boot():
    init_schema()

# ========= Helpers =========
TEMPLATES_DIR = Path(__file__).parent / "templates"

def money(n):
    try:
        return f"${float(n):,.2f}"
    except Exception:
        return n

# ========= Rutas =========

# Home: Dashboard simple con listado de clientes + conteos
@app.route("/")
def home():
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                SELECT id, nombre, telefono, documento, fecha_registro
                FROM clientes
                ORDER BY id DESC;
            """)
            clientes = cur.fetchall()

            cur.execute("SELECT COUNT(*) FROM clientes;")
            total_clientes = cur.fetchone()[0]

            cur.execute("SELECT COALESCE(SUM(monto),0) FROM pagos;")
            total_recaudado = cur.fetchone()[0]

        # Si quieres abrir con 'inicio_logo.html', cambia abajo 'inicio.html' por 'inicio_logo.html'
        return render_template(
            "inicio.html",
            clientes=clientes,
            total_clientes=total_clientes,
            total_recaudado=money(total_recaudado),
        )
    finally:
        conn.close()

# -------- Login (opcional, sin bloqueo de rutas) --------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")
    # Aquí podrías validar credenciales si más adelante agregas una tabla usuarios
    flash("Inicio de sesión simulado.", "info")
    return redirect(url_for("home"))

# -------- Clientes --------
@app.route("/clientes/nuevo", methods=["GET", "POST"])
def cliente_nuevo():
    if request.method == "GET":
        return render_template("nuevo.html")
    # POST → crear cliente
    nombre = request.form.get("nombre", "").strip()
    telefono = request.form.get("telefono", "").strip()
    documento = request.form.get("documento", "").strip()

    if not nombre:
        flash("El nombre es obligatorio.", "warning")
        return redirect(url_for("cliente_nuevo"))

    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO clientes (nombre, telefono, documento, fecha_registro)
                VALUES (%s, %s, %s, %s);
            """, (nombre, telefono, documento, date.today()))
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
                    SELECT id, nombre, telefono, documento, fecha_registro
                    FROM clientes WHERE id=%s;
                """, (cliente_id,))
                cliente = cur.fetchone()
                if not cliente:
                    flash("Cliente no encontrado.", "warning")
                    return redirect(url_for("home"))
            return render_template("editar_cliente.html", cliente=cliente)

        # POST → actualizar
        nombre = request.form.get("nombre", "").strip()
        telefono = request.form.get("telefono", "").strip()
        documento = request.form.get("documento", "").strip()

        if not nombre:
            flash("El nombre es obligatorio.", "warning")
            return redirect(url_for("cliente_editar", cliente_id=cliente_id))

        with conn, conn.cursor() as cur:
            cur.execute("""
                UPDATE clientes
                SET nombre=%s, telefono=%s, documento=%s
                WHERE id=%s;
            """, (nombre, telefono, documento, cliente_id))
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

        # 'pagos.html' puede mostrar lista y formulario de alta
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
    metodo = request.form.get("metodo", "").strip()
    nota = request.form.get("nota", "").strip()

    if not cliente_id or not monto:
        flash("Cliente y monto son obligatorios.", "warning")
        return redirect(url_for("pagos_listado"))

    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO pagos (cliente_id, monto, fecha_pago, metodo, nota)
                VALUES (%s, %s, %s, %s, %s);
            """, (int(cliente_id), float(monto), date.today(), metodo, nota))
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

        # POST → actualizar
        cliente_id = request.form.get("cliente_id")
        monto = request.form.get("monto")
        metodo = request.form.get("metodo", "").strip()
        nota = request.form.get("nota", "").strip()

        if not cliente_id or not monto:
            flash("Cliente y monto son obligatorios.", "warning")
            return redirect(url_for("pago_editar", pago_id=pago_id))

        with conn, conn.cursor() as cur:
            cur.execute("""
                UPDATE pagos
                SET cliente_id=%s, monto=%s, metodo=%s, nota=%s
                WHERE id=%s;
            """, (int(cliente_id), float(monto), metodo, nota, pago_id))
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

# -------- Salud --------
@app.route("/health")
def health():
    try:
        conn = get_connection()
        conn.close()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}, 500

# -------- Main --------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
