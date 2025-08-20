from flask import Flask, render_template, request, redirect, url_for, session, flash
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'secreto'

# Conexión a la base de datos Neon
DB_URL = "postgresql://neondb_owner:npg_3owpfIUOAT0a@ep-soft-bush-acv2a8v4-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

def get_db_connection():
    conn = psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)
    return conn

# LOGIN
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        usuario = request.form.get("usuario")
        contraseña = request.form.get("contraseña")

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM usuarios WHERE usuario=%s AND contrasena=%s;", (usuario, contraseña))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user:
            session["usuario"] = usuario
            return redirect(url_for("inicio"))
        else:
            error = "Usuario o contraseña incorrectos"

    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.pop("usuario", None)
    return redirect(url_for("login"))

# INICIO
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
            flash("Efectivo diario registrado correctamente")

    # Traer clientes
    cur.execute("SELECT * FROM clientes ORDER BY id ASC;")
    clientes = cur.fetchall()

    # Calcular deuda actual de cada cliente (monto prestado - suma pagos)
    for cliente in clientes:
        cur.execute("SELECT COALESCE(SUM(monto),0) as total_pagos FROM pagos WHERE cliente_id=%s;", (cliente['id'],))
        pagos_cliente = cur.fetchone()
        cliente['deuda_actual'] = float(cliente['monto_prestado']) - float(pagos_cliente['total_pagos'])

    # Total de deudas
    total_deuda = sum([c['deuda_actual'] for c in clientes])

    # Efectivo diario
    cur.execute("SELECT * FROM efectivo_diario ORDER BY fecha DESC;")
    efectivo_diario = cur.fetchall()

    # Total de efectivo diario
    total_efectivo = sum([e['monto'] for e in efectivo_diario])

    # Total combinado deuda + efectivo
    total_combinado = total_deuda + total_efectivo

    cur.close()
    conn.close()
    return render_template("inicio.html",
                           clientes=clientes,
                           efectivo_diario=efectivo_diario,
                           total_deuda=total_deuda,
                           total_efectivo=total_efectivo,
                           total_combinado=total_combinado)

# NUEVO CLIENTE
@app.route("/nuevo", methods=["GET", "POST"])
def nuevo():
    if "usuario" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        nombre = request.form.get("nombre")
        monto_prestado = request.form.get("monto_prestado")
        observacion = request.form.get("observacion")
        fecha = request.form.get("fecha") or datetime.today().strftime('%Y-%m-%d')

        if not nombre or not monto_prestado:
            flash("Nombre y monto prestado son obligatorios")
            return redirect(url_for("nuevo"))

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO clientes (nombre, monto_prestado, fecha_registro, observacion, deuda_actual)
            VALUES (%s, %s, %s, %s, %s);
        """, (nombre, monto_prestado, fecha, observacion, monto_prestado))
        conn.commit()
        cur.close()
        conn.close()
        flash("Cliente registrado correctamente")
        return redirect(url_for("inicio"))

    return render_template("nuevo_cliente.html")

# REGISTRAR PAGO
@app.route("/pago/<int:cliente_id>", methods=["POST"])
def pago(cliente_id):
    if "usuario" not in session:
        return redirect(url_for("login"))

    monto = request.form.get("monto")
    if monto:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO pagos (cliente_id, monto) VALUES (%s, %s);", (cliente_id, monto))
        conn.commit()
        cur.close()
        conn.close()
        flash("Pago registrado correctamente")
    return redirect(url_for("inicio"))

if __name__ == "__main__":
    app.run(debug=True)
