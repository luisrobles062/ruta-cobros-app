from flask import Flask, render_template, request, redirect, session, url_for
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'clave_secreta'

# Conexión a la base de datos PostgreSQL en Neon
def get_db_connection():
    conn = psycopg2.connect(
        "dbname=neondb user=neondb_owner password=npg_CwJqDX7z9AaO host=ep-cold-meadow-acvlsfm5-pooler.sa-east-1.aws.neon.tech port=5432 sslmode=require",
        cursor_factory=RealDictCursor
    )
    return conn

# Ruta de inicio de sesión
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['usuario'] == 'admin' and request.form['contrasena'] == 'admin':
            session['usuario'] = request.form['usuario']
            return redirect('/inicio')
        else:
            return render_template('login.html', error='Credenciales incorrectas')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

# Vista principal de clientes
@app.route('/inicio')
def inicio():
    if 'usuario' not in session:
        return redirect('/')

    filtro = request.args.get('filtro', '')
    conn = get_db_connection()
    cur = conn.cursor()

    if filtro:
        cur.execute("SELECT * FROM clientes WHERE nombre ILIKE %s ORDER BY id DESC", (f'%{filtro}%',))
    else:
        cur.execute("SELECT * FROM clientes ORDER BY id DESC")

    clientes = cur.fetchall()

    cur.execute("SELECT * FROM pagos ORDER BY fecha DESC")
    pagos = cur.fetchall()

    conn.close()
    return render_template('inicio.html', clientes=clientes, pagos=pagos, filtro=filtro)

# Registrar nuevo cliente
@app.route('/nuevo', methods=['GET', 'POST'])
def nuevo_cliente():
    if 'usuario' not in session:
        return redirect('/')

    if request.method == 'POST':
        nombre = request.form['nombre']
        monto_prestado = float(request.form['monto_prestado'])
        porcentaje = float(request.form['porcentaje'])
        deuda_actual = monto_prestado + (monto_prestado * porcentaje / 100)
        fecha = datetime.now().s
