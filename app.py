from flask import Flask, render_template, request, redirect, url_for, session, flash
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'secreto'

# --- Configuración de la base de datos Neon ---
DB_HOST = "tudb.neon.tech"
DB_NAME = "neondb"
DB_USER = "neondb_owner"
DB_PASS = "tu_contraseña"
DB_PORT = "5432"

def get_db_connection():
    conn = psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        port=DB_PORT,
        cursor_factory=RealDictCursor
    )
    return conn

# --- Rutas ---

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form.get("usuario")
        contrasena = request.form.get("contrasena")
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM usuarios WHERE usuario=%s AND contrasena=%s;", (usuario, contrasena))
        user = cur.fetchone()
        cur.close()
        conn.close()
        if user:
            session['usuario'] = usuario
            return redirect(url_for("inicio"))
        else:
            flash("Usuario o contraseña incorrectos")
            return redirect(url_for("login"))
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

    # Traer clientes
    cur.execute("SELECT * FROM clientes ORDER BY id;")
    clientes = cur.fetchall()

    # Traer pagos
    cur.execute("SELECT * FROM pagos ORDER BY fecha_pago;")
    pagos = cur.fetchall()

    # Calcular total de deuda
    total_deuda = sum([c['deuda_actual'] for c in clientes])

    # Calcular total efectivo (pagos)
    total_efectivo = sum([p['monto'] for p in pagos])

    total_combinado = total_deuda + total_efectivo

    cur.close()
    conn.close()

    return render_template("inicio.html", clientes=clientes, pagos=pagos,
                           total_deuda=total_deuda, total_efectivo=total_efectivo,
                           total_combinado=total_combinado)

@app.route("/pago/<int:cliente_id>", methods=["POST"])
def pago(cliente_id):
    if "usuario" not in session:
        return redirect(url_for("login"))

    monto = request.form.get("monto")
    if not monto:
        flash("Debe ingresar un monto")
        return redirect(url_for("inicio"))

    conn = get_db_connection()
    cur = conn.cursor()
    # Insertar pago
    cur.execute("""
        INSERT INTO pagos (cliente_id, monto, fecha_pago)
        VALUES (%s, %s, %s)
        """, (cliente_id, monto, datetime.today().strftime('%Y-%m-%d')))
    # Actualizar deuda del cliente
    cur.execute("""
        UPDATE clientes
        SET deuda_actual = deuda_actual - %s
        WHERE id = %s
    """, (monto, cliente_id))
    conn.commit()
    cur.close()
    conn.close()
    flash("Pago registrado correctamente")
    return redirect(url_for("inicio"))

# --- NUEVA RUTA EFECTIVO DIARIO ---
@app.route("/efectivo", methods=["GET", "POST"])
def efectivo():
    if "usuario" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()
    cur = conn.cursor()

    # Registrar efectivo diario
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

    # Traer historial
    cur.execute("SELECT * FROM efectivo_diario ORDER BY fecha DESC;")
    efectivo_diario = cur.fetchall()
    total_efectivo = sum([e['monto'] for e in efectivo_diario])

    cur.close()
    conn.close()

    return render_template("efectivo.html", efectivo_diario=efectivo_diario, total_efectivo=total_efectivo, datetime=datetime)

# --- Ejecutar la app ---
if __name__ == "__main__":
    app.run(debug=True)
