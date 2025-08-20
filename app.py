from flask import Flask, render_template, request, redirect, url_for, flash, session
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

app = Flask(__name__)
app.secret_key = "secreto"

# Configuración de conexión a PostgreSQL
DB_URL = "postgresql://neondb_owner:npg_3owpfIUOAT0a@ep-soft-bush-acv2a8v4-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

def get_db_connection():
    conn = psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)
    return conn

@app.route("/")
def index():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form.get("usuario")
        password = request.form.get("password")
        if usuario == "admin" and password == "admin":
            session["usuario"] = usuario
            return redirect(url_for("inicio"))
        else:
            flash("Usuario o contraseña incorrectos")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/inicio", methods=["GET", "POST"])
def inicio():
    if "usuario" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()
    cur = conn.cursor()

    # Registrar efectivo diario si viene POST
    if request.method == "POST":
        fecha_efectivo = request.form.get("fecha_efectivo") or datetime.today().strftime('%Y-%m-%d')
        monto_efectivo = request.form.get("monto_efectivo")
        if monto_efectivo:
            cur.execute("""
                INSERT INTO efectivo_diario (fecha, monto)
                VALUES (%s, %s);
            """, (fecha_efectivo, monto_efectivo))
            conn.commit()
            return redirect(url_for("inicio"))

    # Traer clientes
    cur.execute("SELECT * FROM clientes ORDER BY id ASC;")
    clientes = cur.fetchall()

    # Calcular deuda actual de cada cliente (monto prestado - suma pagos)
    for cliente in clientes:
        cur.execute("SELECT COALESCE(SUM(monto),0) as total_pagos FROM pagos WHERE cliente_id=%s;", (cliente['id'],))
        pagos_cliente = cur.fetchone()
        cliente['deuda_actual'] = float(cliente['monto_prestado']) - float(pagos_cliente['total_pagos'])

    # Total deuda actual
    total_deuda = sum([c['deuda_actual'] for c in clientes])

    # Total efectivo diario
    cur.execute("SELECT SUM(monto) AS total FROM efectivo_diario;")
    total_efectivo = cur.fetchone()['total'] or 0

    # Total combinado deuda + efectivo
    total_combinado = total_deuda + total_efectivo

    cur.close()
    conn.close()

    return render_template(
        "inicio.html",
        clientes=clientes,
        total_deuda=total_deuda,
        total_efectivo=total_efectivo,
        total_combinado=total_combinado,
        datetime=datetime
    )

@app.route("/nuevo", methods=["GET", "POST"])
def nuevo():
    if "usuario" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        nombre = request.form.get("nombre")
        monto_prestado = request.form.get("monto")
        fecha_registro = request.form.get("fecha") or datetime.today().strftime('%Y-%m-%d')
        observacion = request.form.get("observacion") or ""
        deuda_actual = monto_prestado

        if nombre and monto_prestado:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO clientes (nombre, monto_prestado, fecha_registro, observacion, deuda_actual)
                VALUES (%s, %s, %s, %s, %s);
            """, (nombre, monto_prestado, fecha_registro, observacion, deuda_actual))
            conn.commit()
            cur.close()
            conn.close()
            flash("Cliente registrado correctamente")
            return redirect(url_for("inicio"))
        else:
            flash("Nombre y monto son obligatorios")

    return render_template("nuevo_cliente.html", datetime=datetime)

@app.route("/registrar_pago/<int:cliente_id>", methods=["POST"])
def registrar_pago(cliente_id):
    if "usuario" not in session:
        return redirect(url_for("login"))

    monto_pago = request.form.get("monto_pago")
    if monto_pago:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO pagos (cliente_id, monto)
            VALUES (%s, %s);
        """, (cliente_id, monto_pago))
        conn.commit()
        cur.close()
        conn.close()
        flash("Pago registrado correctamente")
    return redirect(url_for("inicio"))

if __name__ == "__main__":
    app.run(debug=True)
