from flask import Flask, render_template, request, redirect, session, url_for, flash
import sqlite3
import os

app = Flask(__name__)
app.secret_key = 'clave_secreta'

DB_PATH = 'cobros.db'

def obtener_conexion():
    return sqlite3.connect(DB_PATH)

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        contraseña = request.form['contraseña']
        if usuario == 'admin' and contraseña == 'admin':
            session['usuario'] = usuario
            return redirect('/inicio')
        else:
            flash('Credenciales incorrectas', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('usuario', None)
    return redirect('/')

@app.route('/inicio', methods=['GET', 'POST'])
def inicio():
    if 'usuario' not in session:
        return redirect('/')

    conn = obtener_conexion()
    cursor = conn.cursor()

    filtro = request.args.get('filtro', '')

    if filtro:
        cursor.execute("""
            SELECT * FROM clientes
            WHERE nombre LIKE ?
            ORDER BY fecha DESC
        """, ('%' + filtro + '%',))
    else:
        cursor.execute("SELECT * FROM clientes ORDER BY fecha DESC")

    clientes = cursor.fetchall()

    if request.method == 'POST':
        cliente_id = request.form['cliente_id']
        pago = float(request.form['pago'])

        # Registrar pago
        cursor.execute("INSERT INTO pagos (cliente_id, monto_pagado, fecha_pago) VALUES (?, ?, DATE('now'))",
                       (cliente_id, pago))
        
        # Actualizar deuda
        cursor.execute("UPDATE clientes SET deuda_actual = deuda_actual - ? WHERE id = ?",
                       (pago, cliente_id))
        conn.commit()
        
        return redirect('/inicio')

    conn.close()
    return render_template('inicio.html', clientes=clientes, filtro=filtro)

@app.route('/nuevo', methods=['GET', 'POST'])
def nuevo():
    if 'usuario' not in session:
        return redirect('/')

    if request.method == 'POST':
        fecha = request.form['fecha']
        nombre = request.form['nombre']
        monto = request.form['monto']
        porcentaje = request.form['porcentaje']
        observaciones = request.form['observaciones']

        try:
            monto = float(monto)
            porcentaje = float(porcentaje)
            deuda = monto + (monto * (porcentaje / 100))
        except ValueError:
            flash('Monto o porcentaje inválido', 'error')
            return redirect('/nuevo')

        conn = obtener_conexion()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO clientes (fecha, nombre, monto_prestado, porcentaje, deuda_actual, observaciones)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (fecha, nombre, monto, porcentaje, deuda, observaciones))
        conn.commit()
        conn.close()
        return redirect('/inicio')

    return render_template('nuevo.html')

@app.route('/pagos')
def pagos():
    if 'usuario' not in session:
        return redirect('/')

    conn = obtener_conexion()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT pagos.id, clientes.nombre, pagos.monto_pagado, pagos.fecha_pago
        FROM pagos
        JOIN clientes ON pagos.cliente_id = clientes.id
        ORDER BY pagos.fecha_pago DESC
    """)
    pagos = cursor.fetchall()
    conn.close()
    return render_template('pagos.html', pagos=pagos)

if __name__ == '__main__':
    app.run(debug=True)
