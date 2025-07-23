from flask import Flask, render_template, request, redirect, url_for, session, g
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'clave_secreta'

DATABASE = 'cobros.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# ---------------------- LOGIN ---------------------- #

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        contraseña = request.form['contraseña']
        if usuario == 'admin' and contraseña == 'admin':
            session['usuario'] = usuario
            return redirect('/inicio')
        else:
            return render_template('login.html', error='Usuario o contraseña incorrectos.')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

# ---------------------- INICIO ---------------------- #

@app.route('/inicio')
def inicio():
    if 'usuario' not in session:
        return redirect('/')
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, fecha, nombre, monto, porcentaje, deuda, observaciones FROM clientes")
    clientes = cursor.fetchall()
    return render_template('inicio.html', clientes=clientes)

# ---------------------- REGISTRAR NUEVO CLIENTE ---------------------- #

@app.route('/nuevo', methods=['GET', 'POST'])
def nuevo():
    if 'usuario' not in session:
        return redirect('/')
    if request.method == 'POST':
        fecha = request.form['fecha']
        nombre = request.form['nombre']
        monto = float(request.form['monto'])
        porcentaje = float(request.form['porcentaje'])
        deuda = monto + (monto * (porcentaje / 100))
        observaciones = request.form['observaciones']
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO clientes (fecha, nombre, monto, porcentaje, deuda, observaciones) VALUES (?, ?, ?, ?, ?, ?)",
                       (fecha, nombre, monto, porcentaje, deuda, observaciones))
        conn.commit()
        return redirect('/inicio')
    return render_template('nuevo.html')

# ---------------------- REGISTRAR PAGO ---------------------- #

@app.route('/pago/<int:id>', methods=['POST'])
def registrar_pago(id):
    if 'usuario' not in session:
        return redirect('/')
    monto_pagado = float(request.form['monto_pagado'])
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT deuda FROM clientes WHERE id = ?", (id,))
    resultado = cursor.fetchone()
    if resultado:
        nueva_deuda = max(0, resultado[0] - monto_pagado)
        cursor.execute("UPDATE clientes SET deuda = ? WHERE id = ?", (nueva_deuda, id))
        conn.commit()
    return redirect('/inicio')

# ---------------------- EJECUTAR ---------------------- #

if __name__ == '__main__':
    app.run(debug=True)
