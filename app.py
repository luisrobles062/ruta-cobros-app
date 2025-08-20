from flask import Flask, render_template, request, redirect, url_for, session, flash
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'secreto'

# Configuración de la base de datos PostgreSQL (Neon)
DB_HOST = "ep-soft-bush-acv2a8v4-pooler.sa-east-1.aws.neon.tech"
DB_NAME = "neondb"
DB_USER = "neondb_owner"
DB_PASS = "npg_3owpfIUOAT0a"
DB_PORT = "5432"

def get_db_connection():
    conn = psycopg2.connect(
        host=DB_HOST,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        port=DB_PORT,
        cursor_factory=RealDictCursor
    )
    return conn

# Ruta de login
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        contrasena = request.form['contrasena']
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM usuarios WHERE usuario=%s AND contrasena=%s", (usuario, contrasena))
        user = cur.fetchone()
        cur.close()
        conn.close()
        if user:
            session['usuario'] = user['usuario']
            return redirect(url_for('inicio'))
        else:
            flash("Usuario o contraseña incorrectos", "error")
            return redirect(url_for('login'))
    return render_template('login.html')

# Ruta de logout
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# Página principal: lista de clientes y efectivo diario
@app.route('/inicio', methods=['GET', 'POST'])
def inicio():
    if 'usuario' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()

    # Registrar efectivo diario
    if request.method == 'POST' and 'monto_efectivo' in request.form:
        fecha = request.form['fecha_efectivo']
        monto = request.form['monto_efectivo']
        if monto and monto.strip() != '':
            cur.execute("INSERT INTO efectivo_diario (fecha, monto) VALUES (%s, %s)", (fecha, monto))
            conn.commit()

    # Traer clientes
    cur.execute("SELECT * FROM clientes ORDER BY id")
    clientes = cur.fetchall()

    # Traer efectivo diario
    cur.execute("SELECT * FROM efectivo_diario ORDER BY id")
    efectivo_diario = cur.fetchall()

    # Calcular totales
    total_deuda = sum(c['deuda_actual'] for c in clientes)
    total_efectivo = sum(e['monto'] for e in efectivo_diario)
    total_combinado = total_deuda + total_efectivo

    cur.close()
    conn.close()

    return render_template('inicio.html',
                           clientes=clientes,
                           efectivo_diario=efectivo_diario,
                           total_deuda=total_deuda,
                           total_efectivo=total_efectivo,
                           total_combinado=total_combinado,
                           datetime=datetime)

# Registrar pago de un cliente
@app.route('/pago/<int:cliente_id>', methods=['POST'])
def pago(cliente_id):
    if 'usuario' not in session:
        return redirect(url_for('login'))

    monto = request.form['monto']
    fecha_pago = datetime.utcnow().date()

    conn = get_db_connection()
    cur = conn.cursor()

    # Insertar pago
    cur.execute("INSERT INTO pagos (cliente_id, monto, fecha_pago) VALUES (%s, %s, %s)",
                (cliente_id, monto, fecha_pago))

    # Actualizar deuda actual
    cur.execute("UPDATE clientes SET deuda_actual = deuda_actual - %s WHERE id=%s", (monto, cliente_id))
    conn.commit()
    cur.close()
    conn.close()

    flash(f"Pago de {monto} registrado correctamente.", "success")
    return redirect(url_for('inicio'))

if __name__ == '__main__':
    app.run(debug=True)
