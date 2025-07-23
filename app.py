from flask import Flask, render_template, request, redirect, session, url_for
import sqlite3
import os

app = Flask(__name__)
app.secret_key = 'clave_secreta'

DATABASE = 'cobros.db'

# ---------- FUNCIONES DE BASE DE DATOS ----------

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# ---------- LOGIN ----------

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        contraseña = request.form['contraseña']
        if usuario == 'admin' and contraseña == 'admin':
            session['usuario'] = usuario
            return redirect('/inicio')
        else:
            return render_template('login.html', error='Usuario o contraseña incorrectos')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

# ---------- INICIO: VER CLIENTES ----------

@app.route('/inicio')
def inicio():
    if 'usuario' not in session:
        return redirect('/')
    conn = get_db_connection()
    clientes = conn.execute('SELECT * FROM clientes').fetchall()
    conn.close()
    return render_template('inicio.html', clientes=clientes)

# ---------- NUEVO CLIENTE ----------

@app.route('/nuevo', methods=['GET', 'POST'])
def nuevo_cliente():
    if 'usuario' not in session:
        return redirect('/')
    if request.method == 'POST':
        nombre = request.form['nombre']
        monto = float(request.form['monto_prestado'])
        fecha = request.form['fecha_inicio']
        observaciones = request.form.get('observaciones', '')
        conn = get_db_connection()
        conn.execute('INSERT INTO clientes (nombre, monto_prestado, deuda_actual, fecha, observaciones) VALUES (?, ?, ?, ?, ?)',
                     (nombre, monto, monto, fecha, observaciones))
        conn.commit()
        conn.close()
        return redirect('/inicio')
    return render_template('nuevo.html')

# ---------- EJECUCIÓN ----------

if __name__ == '__main__':
    if not os.path.exists(DATABASE):
        # Crear base de datos si no existe (opcional)
        conn = get_db_connection()
        conn.execute('''
            CREATE TABLE clientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                monto_prestado REAL NOT NULL,
                deuda_actual REAL NOT NULL,
                fecha TEXT NOT NULL,
                observaciones TEXT
            )
        ''')
        conn.commit()
        conn.close()
    app.run(debug=True)
