from flask import Flask, render_template, request, redirect, session
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'clave_secreta'

def conectar_db():
    return sqlite3.connect('cobros.db')

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        contrasena = request.form['contrasena']
        if usuario == 'admin' and contrasena == 'admin':
            session['usuario'] = usuario
            return redirect('/inicio')
        else:
            return render_template('login.html', error='Credenciales inválidas')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('usuario', None)
    return redirect('/')

@app.route('/inicio', methods=['GET', 'POST'])
def inicio():
    if not session.get('usuario'):
        return redirect('/')
    conn = conectar_db()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    filtro_nombre = request.args.get('filtro_nombre', '').strip()
    if filtro_nombre:
        cursor.execute("SELECT * FROM clientes WHERE nombre LIKE ?", ('%' + filtro_nombre + '%',))
    else:
        cursor.execute("SELECT * FROM clientes")
    clientes = cursor.fetchall()

    conn.close()
    return render_template('inicio.html', clientes=clientes, filtro_nombre=filtro_nombre)

@app.route('/registrar_pago/<int:cliente_id>', methods=['POST'])
def registrar_pago(cliente_id):
    monto = float(request.form['pago'])
    comentario = request.form.get('comentario', '')
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE clientes SET deuda_actual = deuda_actual - ? WHERE id = ?", (monto, cliente_id))
    cursor.execute("INSERT INTO cobros (cliente_id, monto, comentario, fecha) VALUES (?, ?, ?, ?)",
                   (cliente_id, monto, comentario, datetime.now().strftime('%Y-%m-%d')))
    conn.commit()
    conn.close()
    return redirect('/inicio')

@app.route('/pagos/<int:cliente_id>')
def ver_pagos(cliente_id):
    if not session.get('usuario'):
        return redirect('/')
    conn = conectar_db()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT nombre FROM clientes WHERE id = ?", (cliente_id,))
    cliente = cursor.fetchone()
    cursor.execute("SELECT monto, comentario, fecha FROM cobros WHERE cliente_id = ? ORDER BY fecha DESC", (cliente_id,))
    pagos = cursor.fetchall()
    conn.close()
    return render_template('pagos_cliente.html', cliente=cliente, pagos=pagos)

if __name__ == '__main__':
    app.run(debug=True)
