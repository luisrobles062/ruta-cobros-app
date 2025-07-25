from flask import Flask, render_template, request, redirect, session
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'clave_secreta'

def conectar_db():
    return sqlite3.connect('cobros.db')

# ------------------ RUTAS ------------------

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

# Inicio - mostrar todos los clientes y pagos filtrados
@app.route('/inicio')
def inicio():
    if not session.get('usuario'):
        return redirect('/')

    filtro_nombre = request.args.get('filtro', '').strip()

    conn = conectar_db()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if filtro_nombre:
        cursor.execute("SELECT * FROM clientes WHERE nombre LIKE ? ORDER BY nombre ASC", ('%'+filtro_nombre+'%',))
    else:
        cursor.execute("SELECT * FROM clientes ORDER BY nombre ASC")

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

# Editar cliente
@app.route('/editar_cliente/<int:cliente_id>', methods=['GET', 'POST'])
def editar_cliente(cliente_id):
    if not session.get('usuario'):
        return redirect('/')

    conn = conectar_db()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if request.method == 'POST':
        nombre = request.form['nombre']
        deuda = float(request.form['deuda'])
        fecha_inicio = request.form['fecha_inicio']
        observaciones = request.form['observaciones']

        cursor.execute(
            "UPDATE clientes SET nombre = ?, deuda = ?, fecha_inicio = ?, observaciones = ? WHERE id = ?",
            (nombre, deuda, fecha_inicio, observaciones, cliente_id)
        )
        conn.commit()
        conn.close()
        return redirect('/inicio?filtro=' + nombre)

    else:
        cursor.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,))
        cliente = cursor.fetchone()
        conn.close()
        if cliente:
            return render_template('editar_cliente.html', cliente=cliente)
        else:
            return "Cliente no encontrado", 404

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
    return redirect('/inicio?filtro=' + str(cliente_id))

# Editar pago
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

        cursor.execute("SELECT cliente_id, monto FROM cobros WHERE id = ?", (pago_id,))
        pago = cursor.fetchone()

        if pago:
            cliente_id = pago['cliente_id']
            monto_anterior = pago['monto']

            cursor.execute("UPDATE cobros SET monto = ?, comentario = ? WHERE id = ?", (nuevo_monto, nuevo_comentario, pago_id))

            diferencia = monto_anterior - nuevo_monto
            cursor.execute("UPDATE clientes SET deuda = deuda + ? WHERE id = ?", (diferencia, cliente_id))

            conn.commit()
            conn.close()
            return redirect('/inicio?filtro=' + str(cliente_id))
        else:
            conn.close()
            return "Pago no encontrado", 404

    else:
        cursor.execute("SELECT * FROM cobros WHERE id = ?", (pago_id,))
        pago = cursor.fetchone()
        conn.close()
        if pago:
            return render_template('editar_pago.html', pago=pago)
        else:
            return "Pago no encontrado", 404

# Eliminar pago
@app.route('/eliminar_pago', methods=['POST'])
def eliminar_pago():
    if not session.get('usuario'):
        return redirect('/')

    pago_id = request.form['pago_id']

    conn = conectar_db()
    cursor = conn.cursor()

    cursor.execute("SELECT cliente_id, monto FROM cobros WHERE id = ?", (pago_id,))
    pago = cursor.fetchone()

    if pago:
        cliente_id = pago[0]
        monto = pago[1]

        cursor.execute("DELETE FROM cobros WHERE id = ?", (pago_id,))
        cursor.execute("UPDATE clientes SET deuda = deuda + ? WHERE id = ?", (monto, cliente_id))

        conn.commit()
        conn.close()
        return redirect('/inicio?filtro=' + str(cliente_id))
    else:
        conn.close()
        return "Pago no encontrado", 404

# ------------------ CREAR TABLAS SI NO EXISTEN ------------------

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
