from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'clave_secreta'

def conectar_db():
    return sqlite3.connect('cobros.db')

def obtener_total_pagado(cliente_id):
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(monto) FROM cobros WHERE cliente_id = ?", (cliente_id,))
    resultado = cursor.fetchone()[0]
    conn.close()
    return resultado if resultado else 0.0

@app.route('/')
def login():
    return render_template('login.html')

@app.route('/ingresar', methods=['POST'])
def ingresar():
    if request.form['usuario'] == 'admin' and request.form['clave'] == 'cobros2025':
        session['usuario'] = 'admin'
        return redirect('/inicio')
    return redirect('/')

@app.route('/inicio')
def inicio():
    if 'usuario' not in session:
        return redirect('/')
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clientes")
    clientes = cursor.fetchall()

    clientes_actualizados = []
    for cliente in clientes:
        id, nombre, deuda, fecha_inicio, observaciones = cliente
        total_pagado = obtener_total_pagado(id)
        deuda_actual = deuda - total_pagado
        clientes_actualizados.append((id, nombre, deuda, deuda_actual, fecha_inicio, observaciones))

    conn.close()
    return render_template('inicio.html', clientes=clientes_actualizados)

@app.route('/agregar_cliente', methods=['POST'])
def agregar_cliente():
    if 'usuario' not in session:
        return redirect('/')
    nombre = request.form['nombre']
    deuda = float(request.form['deuda'])
    fecha = datetime.now().strftime('%Y-%m-%d')
    observaciones = request.form['observaciones']
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO clientes (nombre, deuda, fecha_inicio, observaciones) VALUES (?, ?, ?, ?)",
                   (nombre, deuda, fecha, observaciones))
    conn.commit()
    conn.close()
    return redirect('/inicio')

@app.route('/registrar_cobro', methods=['POST'])
def registrar_cobro():
    if 'usuario' not in session:
        return redirect('/')
    cliente_id = request.form['cliente_id']
    monto = float(request.form['monto'])
    comentario = request.form['comentario']
    fecha = datetime.now().strftime('%Y-%m-%d')
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO cobros (cliente_id, monto, fecha, comentario) VALUES (?, ?, ?, ?)",
                   (cliente_id, monto, fecha, comentario))
    conn.commit()
    conn.close()
    return redirect('/inicio')

if __name__ == '__main__':
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS clientes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        nombre TEXT,
                        deuda REAL,
                        fecha_inicio TEXT,
                        observaciones TEXT)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS cobros (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        cliente_id INTEGER,
                        monto REAL,
                        fecha TEXT,
                        comentario TEXT)""")
    conn.commit()
    conn.close()
    app.run(debug=True)
