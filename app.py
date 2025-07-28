from flask import Flask, render_template, request, redirect, url_for, session
import psycopg2
import psycopg2.extras
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'clave_secreta'

# Conexión a PostgreSQL en Render
def obtener_conexion():
    return psycopg2.connect(
        host="dpg-d21or4emcj7s73eqk1j0-a.oregon-postgres.render.com",
        database="cobros_db_apyt",
        user="cobros_user",
        password="qf5rdhUywTUKi0qRFvtK2TQrgvaHtBjQ",
        sslmode="require"
    )

# ================= LOGIN =================
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        clave = request.form['clave']
        if usuario == 'admin' and clave == 'admin':
            session['usuario'] = usuario
            return redirect(url_for('inicio'))
        else:
            return render_template('login.html', error='Credenciales incorrectas')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ================= INICIO =================
@app.route('/inicio')
def inicio():
    if 'usuario' not in session:
        return redirect(url_for('login'))

    filtro = request.args.get('filtro', '')

    conn = obtener_conexion()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    if filtro:
        cur.execute("SELECT * FROM clientes WHERE nombre ILIKE %s ORDER BY id DESC", (f"%{filtro}%",))
    else:
        cur.execute("SELECT * FROM clientes ORDER BY id DESC")
    clientes = cur.fetchall()
    conn.close()
    return render_template('inicio.html', clientes=clientes, filtro=filtro)

# ================= NUEVO CLIENTE =================
@app.route('/nuevo', methods=['GET', 'POST'])
def nuevo():
    if 'usuario' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        fecha = request.form['fecha']
        nombre = request.form['nombre']
        monto = float(request.form['monto'])
        porcentaje = float(request.form['porcentaje'])
        observaciones = request.form['observaciones']
        deuda_actual = monto + (monto * porcentaje / 100)

        conn = obtener_conexion()
        cur = conn.cursor()
        cur.execute("INSERT INTO clientes (fecha, nombre, monto_prestado, porcentaje, deuda_actual, observaciones) VALUES (%s, %s, %s, %s, %s, %s)",
                    (fecha, nombre, monto, porcentaje, deuda_actual, observaciones))
        conn.commit()
        conn.close()
        return redirect(url_for('inicio'))
    return render_template('nuevo_cliente.html')

# ================= REGISTRAR PAGO =================
@app.route('/pago/<int:cliente_id>', methods=['POST'])
def registrar_pago(cliente_id):
    if 'usuario' not in session:
        return redirect(url_for('login'))

    pago = float(request.form['pago'])
    fecha_pago = datetime.now()

    conn = obtener_conexion()
    cur = conn.cursor()

    # Insertar pago
    cur.execute("INSERT INTO pagos (cliente_id, pago, fecha_pago) VALUES (%s, %s, %s)",
                (cliente_id, pago, fecha_pago))

    # Actualizar deuda
    cur.execute("UPDATE clientes SET deuda_actual = deuda_actual - %s WHERE id = %s", (pago, cliente_id))

    conn.commit()
    conn.close()
    return redirect(url_for('inicio'))

# ================= VER PAGOS =================
@app.route('/pagos')
def ver_pagos():
    if 'usuario' not in session:
        return redirect(url_for('login'))

    conn = obtener_conexion()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("""
        SELECT pagos.id, clientes.nombre, pagos.pago, pagos.fecha_pago
        FROM pagos
        JOIN clientes ON pagos.cliente_id = clientes.id
        ORDER BY pagos.fecha_pago DESC
    """)
    pagos = cur.fetchall()
    conn.close()

    return render_template('pagos.html', pagos=pagos)

# ================= EJECUTAR =================
if __name__ == '__main__':
    app.run(debug=True)
