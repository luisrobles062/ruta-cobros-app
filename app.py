from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory
import psycopg2
import psycopg2.extras
import os

app = Flask(__name__)

# --- Configuración segura ---
app.secret_key = os.getenv("SECRET_KEY", "secreto")  # usa SECRET_KEY en producción

# Usa variable de entorno si está disponible (recomendado en Render/Neon)
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://neondb_owner:npg_DqyQpk4iBLh3@ep-still-water-adszkvnv-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
)

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.DictCursor)

# ----------------- RUTAS AUX -----------------
@app.get("/health")
def health():
    return jsonify(status="ok")

# Sirve un favicon vacío si no tienes archivo (evita el 404 ruidoso)
@app.get("/favicon.ico")
def favicon():
    static_path = os.path.join(app.root_path, "static")
    ico_path = os.path.join(static_path, "favicon.ico")
    if os.path.exists(ico_path):
        return send_from_directory(static_path, "favicon.ico", mimetype="image/x-icon")
    return ("", 204)

# ----------------- LOGIN -----------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # Soportar JSON y formularios
        data = {}
        if request.is_json:
            data = request.get_json(silent=True) or {}
        else:
            data = request.form or {}

        usuario = data.get("usuario", "").strip()
        contrasena = data.get("contrasena", "").strip()

        if not usuario or not contrasena:
            # No devolvemos 400: mostramos el error y mantenemos 200 para UX
            flash("Por favor, completa usuario y contraseña.")
            return render_template("login.html"), 200

        # Demo fija: admin/admin (ajusta con DB si quieres)
        if usuario == "admin" and contrasena == "admin":
            session["usuario"] = usuario
            return redirect(url_for("inicio"))
        else:
            flash("Usuario o contraseña incorrectos")
            return render_template("login.html"), 200

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ----------------- CLIENTES -----------------
@app.route("/inicio")
def inicio():
    if "usuario" not in session:
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
    if "usuario" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        # Acepta JSON y formulario
        data = request.get_json(silent=True) if request.is_json else request.form

        nombre = (data.get("nombre") or "").strip()
        monto_raw = (data.get("monto") or "").strip()
        observaciones = (data.get("observaciones") or "").strip()

        # Validaciones simples
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

# ----------------- PAGOS -----------------
@app.route("/pago/<int:id>", methods=["POST"])
def registrar_pago(id):
    if "usuario" not in session:
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

# ----------------- INICIALIZACIÓN -----------------
def crear_tabla():
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
    crear_tabla()
    # En Render usarás gunicorn: web: gunicorn app:app
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
