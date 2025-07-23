from flask import Flask, render_template, request, redirect, session, url_for
import sqlite3

app = Flask(__name__)
app.secret_key = 'clave_secreta'

# Conexión a la base de datos
def get_db_connection():
    conn = sqlite3.connect('cobros.db')
    conn.row_factory = sqlite3.Row
    return conn

# Ruta de login
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

# Ruta de logout
@app.route('/logout')
def logout():
    session.pop('usuario', None)
    return redirect('/')

# Página principal con listado de clientes
@app.route('/inicio')
def inicio():
    if 'usuario' not in session:
        return redirect('/')
    conn = get_db_connection()
    clientes = conn.execute('SELECT * FROM clientes').fetchall()
    conn.close()
    return render_template('inicio.html', clientes=clientes)

# Ruta para mostrar el formulario de nuevo cliente
@app.route('/nuevo', methods=['GET', 'POST'])
def nuevo_cliente():
    if 'usuario' not in session:
        return redirect('/')

    if request.method == 'POST':
        nombre = request.form['nombre']
        monto_prestado = float(request.form['monto_prestado'])
        fecha_inicio = request.form['fecha_inicio']
        observaciones = request.form['observaciones']
        deuda = monto_prestado  # Inicialmente igual

        conn = get_db_connection()
        conn.execute('INSERT INTO clientes (nombre, deuda, fecha_inicio, Observaciones) VALUES (?, ?, ?, ?)',
                     (nombre, deuda, fecha_inicio, observaciones))
        conn.commit()
        conn.close()
        return redirect('/inicio')

    return render_template('nuevo.html')
