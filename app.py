from flask import Flask, render_template, request, redirect, session
import sqlite3
from datetime import datetime
import os
import shutil

app = Flask(__name__)
app.secret_key = 'clave_secreta'

def conectar_db():
    return sqlite3.connect('cobros.db')

# Backup automático al iniciar la app
@app.before_first_request
def backup_db():
    try:
        if os.path.exists('cobros.db'):
            shutil.copy('cobros.db', 'cobros_backup.db')
            print("✅ Backup creado: cobros_backup.db")
    except Exception as e:
        print(f"❌ Error haciendo backup: {e}")

# Login
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        clave = request.form['clave']
        if usuario == 'admin' and clave == 'admin':
            session['usuario'] = usuario
            return redirect('/inicio')
        else:
            return render_template('login.html', error='Credenciales inválidas')
    return render_template('login.html')

# Logout
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

# Inicio con lista clientes + total pagado + filtro
@app.route('/inicio')
def inicio():
    if not session.get('usuario'):
        return redirect('/')

    filtro_nombre = request.args.get('filtro', '').strip()

    conn = conectar_db()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if filtro_nombre:
        cursor.execute("""
            SELECT c.*, IFNULL(SUM(p.monto), 0) AS total_pagado
            FROM clientes c
            LEFT JOIN cobros p ON c.id = p.cliente_id
            WHERE c.nombre LIKE ?
            GROUP BY c.id
            ORDER BY c.nombre ASC
        """, ('%' + filtro_nombre + '%',))
    else:
        cursor.execute("""
            SELECT c.*, IFNULL(SUM(p.monto), 0) AS total_pagado
            FROM clientes c
            LEFT JOIN cobros p ON c.id = p.cliente_id
            GROUP BY c.id
            ORDER BY c.nombre ASC
        """)

    clientes = cursor.fetchall()
    pagos = []
    if filtro_nombre and clientes:
        cliente_id = clientes[0]['id']
        cursor.execute("SELECT * FROM cobros WHERE cliente_id = ? ORDER BY fecha DESC", (cliente_id,))
        pagos = cursor.fetchall()

    conn.close()
    return render_template('inicio.html', clientes=clientes, pagos=pagos, filtro=filtro_nombre)

# Nuevo cliente
@app.route('/nuevo', methods=['GET', 'POST'])
def nuevo_cliente():
    if not session.get('usuario'):
        return redirect('/')

    if request.method == 'POST':
        nombre = request.form['nombre']
        deuda = float(request.form['deuda'])
        fecha_inicio = request.form['fecha_inicio']
        observaciones = request.form['observaciones']

        conn = conectar_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO clientes (nombre, deuda, fecha_inicio, observaciones) VALUES (?, ?, ?, ?)",
            (nombre, deuda, fecha_inicio, observaciones)
        )
        conn.commit()
        conn.close()
        return redirect('/inicio')

    return render_template('nuevo.html')

# Registrar pago
@app.route('/pago', methods=['POST'])
def registrar_pago():
    if not session.get('usuario'):
        return redirect('/')

    cliente_id = request.form['cliente_id']
    monto = float(request.form['monto'])
    comentario = request.form.get('comentario', '')

    conn = conectar_db()
    cursor = conn.cursor()

    cursor.execute("UPDATE clientes SET deuda = deuda - ? WHERE id = ?", (monto, cliente_id))
    cursor.execute(
        "INSERT INTO cobros (cliente_id, monto, comentario, fecha) VALUES (?, ?, ?, ?)",
        (cliente_id, monto, comentario, datetime.now().strftime('%Y-%m-%d'))
    )

    conn.commit()
    conn.close()
    return redirect('/inicio')

# Editar pago
@app.route('/editar_pago/<int:id>', methods=['POST'])
def editar_pago(id):
    if not session.get('usuario'):
        return redirect('/')

    nuevo_monto = float(request.form['nuevo_monto'])
    nuevo_comentario = request.form.get('nuevo_comentario', '')

    conn = conectar_db()
    cursor = conn.cursor()

    cursor.execute("SELECT cliente_id, monto FROM cobros WHERE id = ?", (id,))
    pago_anterior = cursor.fetchone()

    if pago_anterior:
        diferencia = nuevo_monto - pago_anterior[1]
        cliente_id = pago_anterior[0]

        cursor.execute("UPDATE cobros SET monto = ?, comentario = ? WHERE id = ?",
                       (nuevo_monto, nuevo_comentario, id))
        cursor.execute("UPDATE clientes SET deuda = deuda - ? WHERE id = ?", (diferencia, cliente_id))

    conn.commit()
    conn.close()
    return redirect('/inicio')

# Eliminar pago
@app.route('/eliminar_pago/<int:id>', methods=['POST'])
def eliminar_pago(id):
    if not session.get('usuario'):
        return redirect('/')

    conn = conectar_db()
    cursor = conn.cursor()

    cursor.execute("SELECT cliente_id, monto FROM cobros WHERE id = ?", (id,))
    pago = cursor.fetchone()

    if pago:
        cliente_id = pago[0]
        monto = pago[1]

        cursor.execute("DELETE FROM cobros WHERE id = ?", (id,))
        cursor.execute("UPDATE clientes SET deuda = deuda + ? WHERE id = ?", (monto, cliente_id))

    conn.commit()
    conn.close()
    return redirect('/inicio')

# Crear tablas si no existen
if __name__ == '__main__':
    conn = conectar_db()
    cursor = conn.cursor()

    cursor.execute('''CREATE TABLE IF NOT EXISTS clientes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT,
        deuda REAL,
        fecha_inicio TEXT,
        observaciones TEXT
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS cobros (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER,
        monto REAL,
        comentario TEXT,
        fecha TEXT DEFAULT (date('now'))
    )''')

    conn.commit()
    conn.close()

    app.run(debug=True)
