from flask import Flask, render_template, request, redirect, session, url_for
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'clave_secreta'

def conectar_db():
    return sqlite3.connect('cobros.db')

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

# Inicio - mostrar todos los clientes y filtrado
@app.route('/inicio', methods=['GET'])
def inicio():
    if not session.get('usuario'):
        return redirect('/')

    filtro = request.args.get('filtro', '')

    conn = conectar_db()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if filtro:
        cursor.execute("SELECT * FROM clientes WHERE nombre LIKE ? ORDER BY nombre ASC", ('%' + filtro + '%',))
    else:
        cursor.execute("SELECT * FROM clientes ORDER BY nombre ASC")
    clientes = cursor.fetchall()

    conn.close()
    return render_template('inicio.html', clientes=clientes, filtro=filtro)

# Ver pagos de cliente
@app.route('/pagos/<int:cliente_id>')
def pagos(cliente_id):
    if not session.get('usuario'):
        return redirect('/')

    conn = conectar_db()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,))
    cliente = cursor.fetchone()

    cursor.execute("SELECT * FROM cobros WHERE cliente_id = ? ORDER BY fecha DESC", (cliente_id,))
    pagos = cursor.fetchall()

    conn.close()
    return render_template('clientes_de_pagos.html', cliente=cliente, pagos=pagos)

# Nuevo cliente
@app.route('/nuevo', methods=['GET', 'POST'])
def nuevo_cliente():
    if not session.get('usuario'):
        return redirect('/')

    if request.method == 'POST':
        nombre = request.form['nombre']
        monto_prestado = float(request.form['monto_prestado'])
        fecha_inicio = request.form['fecha_inicio']
        observaciones = request.form['observaciones']

        conn = conectar_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO clientes (nombre, monto_prestado, deuda_actual, fecha_inicio, observaciones) VALUES (?, ?, ?, ?, ?)",
            (nombre, monto_prestado, monto_prestado, fecha_inicio, observaciones)
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

    # Actualizar deuda_actual restando pago solo si no está anulado
    cursor.execute("UPDATE clientes SET deuda_actual = deuda_actual - ? WHERE id = ?", (monto, cliente_id))
    cursor.execute(
        "INSERT INTO cobros (cliente_id, monto, comentario, fecha, anulado) VALUES (?, ?, ?, ?, 0)",
        (cliente_id, monto, comentario, datetime.now().strftime('%Y-%m-%d'))
    )

    conn.commit()
    conn.close()
    return redirect(url_for('pagos', cliente_id=cliente_id))

# Mostrar formulario para editar pago
@app.route('/editar_pago/<int:pago_id>', methods=['GET', 'POST'])
def editar_pago(pago_id):
    if not session.get('usuario'):
        return redirect('/')

    conn = conectar_db()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if request.method == 'POST':
        nuevo_monto = float(request.form['monto'])
        nuevo_comentario = request.form.get('comentario', '')

        # Obtener pago actual para actualizar deuda
        cursor.execute("SELECT cliente_id, monto, anulado FROM cobros WHERE id = ?", (pago_id,))
        pago = cursor.fetchone()
        if pago and pago['anulado'] == 0:
            cliente_id = pago['cliente_id']
            monto_antiguo = pago['monto']

            diferencia = nuevo_monto - monto_antiguo

            # Actualizar deuda actual según diferencia
            cursor.execute("UPDATE clientes SET deuda_actual = deuda_actual - ? WHERE id = ?", (diferencia, cliente_id))

            # Actualizar pago
            cursor.execute("UPDATE cobros SET monto = ?, comentario = ? WHERE id = ?", (nuevo_monto, nuevo_comentario, pago_id))

            conn.commit()
            conn.close()
            return redirect(url_for('pagos', cliente_id=cliente_id))

        conn.close()
        return redirect(url_for('inicio'))

    # GET - mostrar formulario con datos actuales del pago
    cursor.execute("SELECT * FROM cobros WHERE id = ?", (pago_id,))
    pago = cursor.fetchone()
    conn.close()

    if pago is None:
        return redirect(url_for('inicio'))

    return render_template('editar_pago.html', pago=pago)

# Deshacer (anular) un pago
@app.route('/deshacer_pago/<int:pago_id>', methods=['POST'])
def deshacer_pago(pago_id):
    if not session.get('usuario'):
        return redirect('/')

    conn = conectar_db()
    cursor = conn.cursor()

    # Obtener pago y verificar que no esté anulado
    cursor.execute("SELECT cliente_id, monto, anulado FROM cobros WHERE id = ?", (pago_id,))
    pago = cursor.fetchone()

    if pago and pago[2] == 0:  # anulado == 0
        cliente_id = pago[0]
        monto = pago[1]

        # Anular pago y aumentar deuda actual
        cursor.execute("UPDATE cobros SET anulado = 1 WHERE id = ?", (pago_id,))
        cursor.execute("UPDATE clientes SET deuda_actual = deuda_actual + ? WHERE id = ?", (monto, cliente_id))

        conn.commit()

    conn.close()
    return redirect(url_for('pagos', cliente_id=cliente_id))

# ------------------ CREAR TABLAS SI NO EXISTEN ------------------

if __name__ == '__main__':
    conn = conectar_db()
    cursor = conn.cursor()

    # Crear tabla 'clientes'
    cursor.execute('''CREATE TABLE IF NOT EXISTS clientes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT,
        monto_prestado REAL,
        deuda_actual REAL,
        fecha_inicio TEXT,
        observaciones TEXT
    )''')

    # Crear tabla 'cobros'
    cursor.execute('''CREATE TABLE IF NOT EXISTS cobros (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER,
        monto REAL,
        comentario TEXT,
        fecha TEXT DEFAULT (date('now')),
        anulado INTEGER DEFAULT 0
    )''')

    conn.commit()
    conn.close()

    app.run(debug=True)
    # Ruta: Ver pagos de un cliente
@app.route('/pagos/<int:cliente_id>')
def pagos(cliente_id):
    if 'usuario' not in session:
        return redirect('/')
    
    conn = sqlite3.connect('cobros.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,))
    cliente = cursor.fetchone()

    cursor.execute("SELECT * FROM pagos WHERE cliente_id = ? ORDER BY fecha DESC", (cliente_id,))
    pagos = cursor.fetchall()

    conn.close()
    return render_template('pagos.html', cliente=cliente, pagos=pagos)

# Ruta: Editar pago
@app.route('/editar_pago/<int:pago_id>', methods=['GET', 'POST'])
def editar_pago(pago_id):
    if 'usuario' not in session:
        return redirect('/')

    conn = sqlite3.connect('cobros.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM pagos WHERE id = ?", (pago_id,))
    pago = cursor.fetchone()

    if request.method == 'POST':
        nuevo_monto = float(request.form['monto'])
        comentario = request.form.get('comentario', '')
        diferencia = nuevo_monto - pago['monto']

        # Actualiza el pago
        cursor.execute("UPDATE pagos SET monto = ?, comentario = ? WHERE id = ?", (nuevo_monto, comentario, pago_id))
        
        # Actualiza la deuda del cliente
        cursor.execute("UPDATE clientes SET deuda_actual = deuda_actual - ? WHERE id = ?", (diferencia, pago['cliente_id']))
        
        conn.commit()
        conn.close()
        return redirect(url_for('pagos', cliente_id=pago['cliente_id']))

    conn.close()
    return render_template('editar_pago.html', pago=pago)

# Ruta: Deshacer pago
@app.route('/deshacer_pago/<int:pago_id>', methods=['POST'])
def deshacer_pago(pago_id):
    if 'usuario' not in session:
        return redirect('/')

    conn = sqlite3.connect('cobros.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Obtener info del pago
    cursor.execute("SELECT * FROM pagos WHERE id = ?", (pago_id,))
    pago = cursor.fetchone()

    if pago:
        # Revertir deuda
        cursor.execute("UPDATE clientes SET deuda_actual = deuda_actual + ? WHERE id = ?", (pago['monto'], pago['cliente_id']))
        # Borrar el pago
        cursor.execute("DELETE FROM pagos WHERE id = ?", (pago_id,))
        conn.commit()

    conn.close()
    return redirect(url_for('pagos', cliente_id=pago['cliente_id']))

