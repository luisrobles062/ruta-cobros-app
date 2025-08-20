from flask import Flask, render_template, request, redirect, url_for, flash, session
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

app = Flask(__name__)
app.secret_key = "supersecreto"

# Conexión a PostgreSQL Neon
DB_URL = "postgresql://neondb_owner:npg_DqyQpk4iBLh3@ep-still-water-adszkvnv-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

def get_db_connection():
    conn = psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)
    return conn

# ---------------------------
# Login
# ---------------------------
@app.route("/", methods=["GET"])
def root():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        usuario = request.form.get("usuario")
        contraseña = request.form.get("contraseña")
        if usuario == "admin" and contraseña == "admin":
            session["usuario"] = usuario
            return redirect(url_for("inicio"))
        else:
            error = "Usuario o contraseña incorrectos"
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------------------------
# Inicio - lista de clientes
# ---------------------------
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

# ---------------------------
# Nuevo Cliente
# ---------------------------
@app.route("/nuevo", methods=["GET", "POST"])
def nuevo():
    if "usuario" not in session:
        return redirect(url_for("login"))
    if request.method == "POST":
        nombre = request.form.get("nombre")
        monto_prestado = request.form.get("monto_prestado")
        fecha = request.form.get("fecha") or datetime.today().strftime('%Y-%m-%d')
        observacion = request.form.get("observacion") or "N/A"

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO clientes (nombre, monto_prestado, fecha, observacion)
            VALUES (%s, %s, %s, %s);
        """, (nombre, monto_prestado, fecha, observacion))
        conn.commit()
        cur.close()
        conn.close()
        flash("Cliente agregado correctamente")
        return redirect(url_for("inicio"))
    return render_template("nuevo_cliente.html")

# ---------------------------
# Editar Cliente
# ---------------------------
@app.route("/editar/<int:id>", methods=["GET", "POST"])
def editar_cliente(id):
    if "usuario" not in session:
        return redirect(url_for("login"))
    conn = get_db_connection()
    cur = conn.cursor()
    if request.method == "POST":
        nombre = request.form.get("nombre")
        monto_prestado = request.form.get("monto_prestado")
        fecha = request.form.get("fecha") or datetime.today().strftime('%Y-%m-%d')
        observacion = request.form.get("observacion") or "N/A"

        cur.execute("""
            UPDATE clientes
            SET nombre=%s, monto_prestado=%s, fecha=%s, observacion=%s
            WHERE id=%s;
        """, (nombre, monto_prestado, fecha, observacion, id))
        conn.commit()
        cur.close()
        conn.close()
        flash("Cliente actualizado correctamente")
        return redirect(url_for("inicio"))
    else:
        cur.execute("SELECT * FROM clientes WHERE id=%s;", (id,))
        cliente = cur.fetchone()
        cur.close()
        conn.close()
        return render_template("editar_cliente.html", cliente=cliente)

# ---------------------------
# Pagos
# ---------------------------
@app.route("/pagos/<int:id>", methods=["GET", "POST"])
def pagos(id):
    if "usuario" not in session:
        return redirect(url_for("login"))
    conn = get_db_connection()
    cur = conn.cursor()
    if request.method == "POST":
        monto = request.form.get("monto")
        fecha_pago = datetime.today().strftime('%Y-%m-%d')
        cur.execute("""
            INSERT INTO pagos (cliente_id, monto, fecha_pago)
            VALUES (%s, %s, %s);
        """, (id, monto, fecha_pago))
        conn.commit()
        cur.close()
        conn.close()
        flash("Pago registrado correctamente")
        return redirect(url_for("inicio"))
    else:
        cur.execute("SELECT * FROM clientes WHERE id=%s;", (id,))
        cliente = cur.fetchone()
        cur.execute("SELECT * FROM pagos WHERE cliente_id=%s ORDER BY fecha_pago DESC;", (id,))
        pagos_cliente = cur.fetchall()
        cur.close()
        conn.close()
        return render_template("pagos.html", cliente=cliente, pagos=pagos_cliente)

# ---------------------------
# Editar Pago
# ---------------------------
@app.route("/editar_pago/<int:id>", methods=["GET", "POST"])
def editar_pago(id):
    if "usuario" not in session:
        return redirect(url_for("login"))
    conn = get_db_connection()
    cur = conn.cursor()
    if request.method == "POST":
        monto = request.form.get("monto")
        cur.execute("UPDATE pagos SET monto=%s WHERE id=%s;", (monto, id))
        conn.commit()
        cur.close()
        conn.close()
        flash("Pago actualizado correctamente")
        return redirect(url_for("inicio"))
    else:
        cur.execute("SELECT * FROM pagos WHERE id=%s;", (id,))
        pago = cur.fetchone()
        cur.close()
        conn.close()
        return render_template("editar_pago.html", pago=pago)

# ---------------------------
# Ejecutar app
# ---------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)
