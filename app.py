from flask import Flask, render_template, request, redirect, url_for, session, g
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = "secreto123"
DATABASE = "cobros.db"

# -------------------------------------
# FUNCIONES DE BASE DE DATOS
# -------------------------------------

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def crear_tabla_clientes():
    with app.app_context():
        db = get_db()
        db.execute("""
            CREATE TABLE IF NOT EXISTS clientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT,
                nombre TEXT,
                monto REAL,
                interes REAL,
                deuda_actual REAL,
                observacion TEXT
            )
        """)
        db.commit()

# -------------------------------------
# LOGIN BÁSICO
# -------------------------------------

@app.route("/", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        usuario = request.form["usuario"]
        contrasena = request.form["contrasena"]
        if usuario == "admin" and contrasena == "admin":
            session["usuario"] = usuario
            return redirect(url_for("inicio"))
        else:
            error = "Credenciales inválidas"
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# -------------------------------------
# INICIO / TABLA DE CLIENTES
# -------------------------------------

@app.route("/inicio", methods=["GET", "POST"])
def inicio():
    if "usuario" not in session:
        return redirect(url_for("login"))

    db = get_db()

    # Registrar pago
    if request.method == "POST":
        cliente_id = request.form.get("cliente_id")
        pago = float(request.form.get("pago", 0))
        if pago > 0:
            db.execute("UPDATE clientes SET deuda_actual = deuda_actual + ? WHERE id = ?", (-pago, cliente_id))
            db.commit()

    # Filtrar por nombre
    filtro_nombre = request.args.get("filtro_nombre", "")
    if filtro_nombre:
        clientes = db.execute(
            "SELECT * FROM clientes WHERE nombre LIKE ? ORDER BY fecha DESC",
            (f"%{filtro_nombre}%",)
        ).fetchall()
    else:
        clientes = db.execute("SELECT * FROM clientes ORDER BY fecha DESC").fetchall()

    return render_template("inicio.html", clientes=clientes, filtro_nombre=filtro_nombre)

# -------------------------------------
# REGISTRAR NUEVO CLIENTE
# -------------------------------------

@app.route("/nuevo", methods=["GET", "POST"])
def nuevo():
    if "usuario" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        fecha = request.form["fecha"]
        nombre = request.form["nombre"]
        monto = float(request.form["monto"])
        interes = float(request.form["interes"])
        deuda_actual = float(request.form["deuda_actual"])
        observacion = request.form["observacion"]

        db = get_db()
        db.execute("""
            INSERT INTO clientes (fecha, nombre, monto, interes, deuda_actual, observacion)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (fecha, nombre, monto, interes, deuda_actual, observacion))
        db.commit()

        return redirect(url_for("inicio"))

    return render_template("nuevo.html")

# -------------------------------------
# INICIALIZAR BASE DE DATOS SI NO EXISTE
# -------------------------------------

if __name__ == "__main__":
    if not os.path.exists(DATABASE):
        open(DATABASE, 'w').close()
    crear_tabla_clientes()
    app.run(debug=True)
