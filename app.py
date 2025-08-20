from flask import Flask, render_template, request, redirect, url_for, session, flash
import psycopg2
import psycopg2.extras
import os

app = Flask(__name__)
app.secret_key = "secreto"

# Conexión a la base Neon PostgreSQL
DATABASE_URL = "postgresql://neondb_owner:npg_DqyQpk4iBLh3@ep-still-water-adszkvnv-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.DictCursor)
    return conn

# ----------------- LOGIN -----------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form["usuario"]
        contrasena = request.form["contrasena"]
        if usuario == "admin" and contrasena == "admin":
            session["usuario"] = usuario
            return redirect(url_for("inicio"))
        else:
            flash("Usuario o contraseña incorrectos")
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
    cur = conn.cursor()
    cur.execute("SELECT * FROM clientes ORDER BY id ASC;")
    clientes = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("inicio.html", clientes=clientes)

@app.route("/nuevo", methods=["GET", "POST"])
def nuevo_cliente():
    if "usuario" not in session:
        return redirect(url_for("login"))
    if request.method == "POST":
        nombre = request.form["nombre"]
        monto = request.form["monto"]
        deuda = monto
        observaciones = request.form.get("observaciones", "")
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO clientes (nombre, monto_prestado, deuda_actual, observaciones) VALUES (%s, %s, %s, %s)",
            (nombre, monto, deuda, observaciones),
        )
        conn.commit()
        cur.close()
        conn.close()
        flash("Cliente agregado correctamente")
        return redirect(url_for("inicio"))
    return render_template("nuevo_cliente.html")

# ----------------- PAGOS -----------------
@app.route("/pago/<int:id>", methods=["POST"])
def registrar_pago(id):
    if "usuario" not in session:
        return redirect(url_for("login"))
    monto_pago = float(request.form["monto_pago"])
    conn = get_db_connection()
    cur = conn.cursor()
    # Obtener deuda actual
    cur.execute("SELECT deuda_actual FROM clientes WHERE id = %s", (id,))
    cliente = cur.fetchone()
    if cliente:
        nueva_deuda = float(cliente[0]) - monto_pago
        if nueva_deuda < 0:
            nueva_deuda = 0
        cur.execute("UPDATE clientes SET deuda_actual = %s WHERE id = %s", (nueva_deuda, id))
        conn.commit()
        flash("Pago registrado correctamente")
    cur.close()
    conn.close()
    return redirect(url_for("inicio"))

# ----------------- INICIALIZACIÓN -----------------
def crear_tabla():
    conn = get_db_connection()
    cur = conn.cursor()
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
    cur.close()
    conn.close()

if __name__ == "__main__":
    crear_tabla()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
