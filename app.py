from flask import Flask, render_template, request, redirect, session, url_for
import psycopg2
import psycopg2.extras
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'clave_secreta'

# Conexión a PostgreSQL usando la variable de entorno DATABASE_URL
DATABASE_URL = os.getenv('DATABASE_URL')

def obtener_conexion():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

# =================== LOGIN ====================
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['usuario'] == 'admin' and request.form['password'] == 'admin':
            session['usuario'] = request.form['usuario']
            return redirect(url_for('inicio'))
        else:
            return render_template('login.html', error='Credenciales inválidas')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# =================== INICIO ====================
@app.route('/inicio')
def inicio():
    if 'usuario' not in session:
        return redirect(url_for('login'))

    filtro = request.args.get('filtro', '')

    conn = obtener_conexion()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    if filtro:
        cur.execute("SELECT * FROM clientes WHERE nombre ILIKE %s ORDER BY id", ('%' + filtro + '%',))
    else:
        cur.execute("SELECT * FROM clientes ORDER BY id")
    clientes = cur.fetchall()

    cur.execute("SELECT SUM(deuda_actual) FROM clientes")
    total_deuda = cur.fetchone()[0] or 0

    conn.close()
    return render_template('inicio.html', clientes=clientes, filtro=filtro, total_deuda=total_deuda)

# =================== NUEVO CLIENTE ====================
@app.route('/nuevo', methods=['GET', 'POST'])
def nuevo():
    if 'usuario' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        fecha = request.form['fecha']
        nombre = request.form['nombre']
        monto = float(request.form['monto'])
        interes = float(request.form['interes'])
        deuda = float(request.form['deuda'])
        observaciones = request.form['observaciones']

        conn = obtener_conexion()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO clientes (fecha, nombre, monto, interes, deuda_actual, observaciones)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (fecha, nombre, monto, interes, deuda, observaciones))
        conn.commit()
        conn.close()
        return redirect(url_for('inicio'))

    return render_template('nuevo_cliente.html')

# =================== REGISTRAR PAGO ====================
@app.route('/pago/<int:cliente_id>', methods=['POST'])
def pago(cliente_id):
    if 'usuario' not in session:
        return redirect(url_for('login'))

    pago = float(request.form['pago'])

    conn = obtener_conexion()
    cur = conn.cursor()
    cur.execute("UPDATE clientes SET deuda_actual = deuda_actual - %s WHERE id = %s", (pago, cliente_id))
    cur.execute("INSERT INTO historial_pagos (cliente_id, pago, fecha_pago) VALUES (%s, %s, %s)",
                (cliente_id, pago, datetime.now()))
    conn.commit()
    conn.close()
    return redirect(url_for('inicio'))

# =================== EJECUCIÓN ====================
if __name__ == '__main__':
    app.run(debug=True)
