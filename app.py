from flask import Flask, render_template, request, redirect, session, url_for
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = 'clave_secreta'

# Conexión a la base de datos PostgreSQL (usando variable de entorno para Railway)
def get_db_connection():
    DATABASE_URL = os.environ.get('DATABASE_URL')
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
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

# Cerrar sesión
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
        fecha = datetime.now().strftime("%Y-%m-%d")

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO clientes (fecha, nombre, monto, porcentaje, deuda, observaciones)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (fecha, nombre, monto_prestado, porcentaje, deuda_actual, ''))
        conn.commit()
        conn.close()

        return redirect('/inicio')

    return render_template('nuevo_cliente.html')

# Registrar pago
@app.route('/pago/<int:cliente_id>', methods=['POST'])
def registrar_pago(cliente_id):
    if 'usuario' not in session:
        return redirect('/')

    pago = float(request.form['pago'])

    conn = get_db_connection()
    cur = conn.cursor()

    # Registrar el pago
    cur.execute("""
        INSERT INTO pagos (cliente_id, monto, fecha)
        VALUES (%s, %s, %s)
    """, (cliente_id, pago, datetime.now()))

    # Actualizar deuda
    cur.execute("UPDATE clientes SET deuda = deuda - %s WHERE id = %s", (pago, cliente_id))

    conn.commit()
    conn.close()

    return redirect('/inicio')

if __name__ == '__main__':
    app.run(debug=True)
