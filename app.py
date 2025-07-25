from flask import Flask, render_template, request, redirect, session, url_for
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'clave_secreta'

# Configuración de conexión a PostgreSQL en Render
DB_URL = 'postgresql://cobros_user:qf5rdhUywTUKi0qRFvtK2TQrgvaHtBjQ@dpg-d21or4emcj7s73eqk1j0-a.oregon-postgres.render.com/cobros_db_apyt'

def get_db_connection():
    return psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['usuario'] == 'admin' and request.form['contrasena'] == 'admin':
            session['usuario'] = 'admin'
            return redirect('/inicio')
        else:
            return render_template('login.html', error='Credenciales incorrectas')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('usuario', None)
    return redirect('/')

@app.route('/inicio')
def inicio():
    if 'usuario' not in session:
        return redirect('/')

    filtro = request.args.get('filtro', '')
    conn = get_db_connection()
    cursor = conn.cursor()

    if filtro:
        cursor.execute("SELECT * FROM clientes WHERE nombre ILIKE %s ORDER BY nombre", ('%' + filtro + '%',))
    else:
        cursor.execute("SELECT * FROM clientes ORDER BY nombre")

    clientes = cursor.fetchall()
    conn.close()
    return render_template('inicio.html', clientes=clientes)

@app.route('/nuevo', methods=['GET', 'POST'])
def nuevo():
    if 'usuario' not in session:
        return redirect('/')
    
    if request.method == 'POST':
        fecha = request.form['fecha']
        nombre = request.form['nombre']
        monto = float(request.form['monto'])
        porcentaje = float(request.form['porcentaje'])
        observaciones = request.form['observaciones']

        deuda = monto + (monto * porcentaje / 100)

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO clientes (fecha, nombre, monto, porcentaje, deuda, observaciones)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (fecha, nombre, monto, porcentaje, deuda, observaciones))
        conn.commit()
        conn.close()
        return redirect('/inicio')

    return render_template('nuevo.html')

@app.route('/registrar_pago', methods=['POST'])
def registrar_pago():
    if 'usuario' not in session:
        return redirect('/')

    cliente_id = request.form['cliente_id']
    monto_pago = float(request.form['monto'])

    conn = get_db_connection()
    cursor = conn.cursor()

    # Actualizar deuda
    cursor.execute("UPDATE clientes SET deuda = deuda - %s WHERE id = %s", (monto_pago, cliente_id))
    # Registrar pago
    cursor.execute("""
        INSERT INTO historial_pagos (cliente_id, pago, fecha_pago)
        VALUES (%s, %s, NOW())
    """, (cliente_id, monto_pago))

    conn.commit()
    conn.close()
    return redirect('/inicio')

@app.route('/pagos')
def pagos():
    if 'usuario' not in session:
        return redirect('/')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT h.id, c.nombre, h.pago AS monto, h.fecha_pago AS fecha
        FROM historial_pagos h
        JOIN clientes c ON h.cliente_id = c.id
        ORDER BY h.fecha_pago DESC
    """)
    pagos = cursor.fetchall()
    conn.close()

    return render_template('pagos.html', pagos=pagos)

@app.route('/pagos_cliente/<int:cliente_id>')
def pagos_cliente(cliente_id):
    if 'usuario' not in session:
        return redirect('/')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT nombre FROM clientes WHERE id = %s", (cliente_id,))
    cliente = cursor.fetchone()

    cursor.execute("""
        SELECT id, pago AS monto, fecha_pago AS fecha
        FROM historial_pagos
        WHERE cliente_id = %s
        ORDER BY fecha_pago DESC
    """, (cliente_id,))
    pagos = cursor.fetchall()
    conn.close()

    return render_template('pagos_cliente.html', pagos=pagos, cliente=cliente)
