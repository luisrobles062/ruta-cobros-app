from flask import Flask, render_template, request, redirect, session
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'clave_secreta'

def get_db_connection():
    conn = sqlite3.connect('cobros.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['usuario'] == 'admin' and request.form['contrasena'] == 'admin':
            session['usuario'] = request.form['usuario']
            return redirect('/inicio')
        else:
            return render_template('login.html', error='Credenciales incorrectas')
    return render_template('login.html')

@app.route('/inicio', methods=['GET', 'POST'])
def inicio():
    if 'usuario' not in session:
        return redirect('/')

    conn = get_db_connection()

    if request.method == 'POST':
        pago = float(request.form['pago'])
        cliente_id = int(request.form['cliente_id'])
        fecha = datetime.now().strftime('%Y-%m-%d')

        conn.execute("INSERT INTO pagos (cliente_id, monto, fecha) VALUES (?, ?, ?)", (cliente_id, pago, fecha))
        conn.execute("UPDATE clientes SET deuda_actual = deuda_actual - ? WHERE id = ?", (pago, cliente_id))
        conn.commit()

    filtro = request.args.get('filtro', '')
    if filtro:
        clientes = conn.execute("SELECT * FROM clientes WHERE nombre LIKE ?", ('%' + filtro + '%',)).fetchall()
    else:
        clientes = conn.execute("SELECT * FROM clientes").fetchall()

    conn.close()
    return render_template('inicio.html', clientes=clientes, filtro=filtro)

@app.route('/logout')
def logout():
    session.pop('usuario', None)
    return redirect('/')

@app.route('/nuevo', methods=['GET', 'POST'])
def nuevo_cliente():
    if 'usuario' not in session:
        return redirect('/')
    
    if request.method == 'POST':
        nombre = request.form['nombre']
        monto = float(request.form['monto'])
        porcentaje = float(request.form['porcentaje'])
        deuda = float(request.form['deuda'])
        fecha = request.form['fecha']
        obs = request.form['observaciones']

        conn = get_db_connection()
        conn.execute("INSERT INTO clientes (fecha, nombre, monto_prestado, porcentaje, deuda_actual, observaciones) VALUES (?, ?, ?, ?, ?, ?)",
                     (fecha, nombre, monto, porcentaje, deuda, obs))
        conn.commit()
        conn.close()
        return redirect('/inicio')

    return render_template('nuevo.html')

@app.route('/editar_pago/<int:id>', methods=['GET', 'POST'])
def editar_pago(id):
    if 'usuario' not in session:
        return redirect('/')

    conn = get_db_connection()
    pago = conn.execute("SELECT * FROM pagos WHERE id = ?", (id,)).fetchone()

    if request.method == 'POST':
        nuevo_monto = float(request.form['nuevo_monto'])
        diferencia = nuevo_monto - pago['monto']

        conn.execute("UPDATE pagos SET monto = ? WHERE id = ?", (nuevo_monto, id))
        conn.execute("UPDATE clientes SET deuda_actual = deuda_actual - ? WHERE id = ?", (diferencia, pago['cliente_id']))
        conn.commit()
        conn.close()
        return redirect('/pagos')

    return render_template('editar_pago.html', pago=pago)

@app.route('/eliminar_pago/<int:id>')
def eliminar_pago(id):
    if 'usuario' not in session:
        return redirect('/')

    conn = get_db_connection()
    pago = conn.execute("SELECT * FROM pagos WHERE id = ?", (id,)).fetchone()
    conn.execute("UPDATE clientes SET deuda_actual = deuda_actual + ? WHERE id = ?", (pago['monto'], pago['cliente_id']))
    conn.execute("DELETE FROM pagos WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return redirect('/pagos')

@app.route('/pagos')
def ver_pagos():
    if 'usuario' not in session:
        return redirect('/')

    conn = get_db_connection()
    pagos = conn.execute("""
        SELECT pagos.id, pagos.monto, pagos.fecha, clientes.nombre
        FROM pagos
        JOIN clientes ON pagos.cliente_id = clientes.id
        ORDER BY pagos.fecha DESC
    """).fetchall()
    conn.close()
    return render_template('pagos.html', pagos=pagos)
