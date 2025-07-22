from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'tu_clave_secreta'

# Conexión con la base de datos
def conectar():
    conn = sqlite3.connect('cobros.db')
    conn.row_factory = sqlite3.Row
    return conn

# Crear tabla clientes si no existe
def crear_tabla():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_prestada TEXT,
            nombre TEXT,
            monto_prestado REAL,
            interes REAL,
            deuda_actual REAL,
            observacion TEXT
        )
    ''')
    conn.commit()
    conn.close()

crear_tabla()

# Ruta de inicio de sesión
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        contraseña = request.form['contraseña']
        if usuario == 'admin' and contraseña == 'admin':
            session['usuario'] = usuario
            return redirect(url_for('inicio'))
        else:
            flash('Usuario o contraseña incorrectos', 'error')
    return render_template('login.html')

# Ruta principal con tabla de clientes
@app.route('/inicio', methods=['GET', 'POST'])
def inicio():
    if 'usuario' not in session:
        return redirect(url_for('login'))

    conn = conectar()
    cursor = conn.cursor()

    # Registrar pagos
    if request.method == 'POST':
        cliente_id = request.form.get('cliente_id')
        pago = float(request.form.get('pago', 0))
        cursor.execute('UPDATE clientes SET deuda_actual = deuda_actual - ? WHERE id = ?', (pago, cliente_id))
        conn.commit()

    # Filtros
    filtro_nombre = request.args.get('filtro_nombre', '')
    cursor.execute("SELECT * FROM clientes WHERE nombre LIKE ?", ('%' + filtro_nombre + '%',))
    clientes = cursor.fetchall()
    conn.close()

    return render_template('inicio.html', clientes=clientes, filtro_nombre=filtro_nombre)

# Cerrar sesión
@app.route('/cerrar')
def cerrar():
    session.pop('usuario', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
