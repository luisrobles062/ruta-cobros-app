from flask import Flask, render_template, request, redirect, session, url_for
import psycopg2
import psycopg2.extras
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'clave_secreta'

# Conexión a PostgreSQL usando DATABASE_URL
DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    DATABASE_URL = 'postgresql://cobros_user:qf5rdhUywTUKi0qRFvtK2TQrgvaHtBjQ@dpg-d21or4emcj7s73eqk1j0-a.oregon-postgres.render.com/cobros_db_apyt'

def obtener_conexion():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

# =================== LOGIN ====================
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['usuario'] == 'admin' and request.form['password'] == 'admin':
            session['usuario'] = request.form['usuario']
            return redirect(url_for('inicio'))
        else:
            return render_template('login.html', error='Credenciales inválidas')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# =================== INICIO ====================
@app.route('/inicio')
def inicio():
    if 'usuario' not in session:
        return redirect(url_for('login'))

    filtro = request.args.get('filtro', '')

    conn = obtener_conexion()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    if filtro:
        cur.execute("SELECT * FROM clientes WHERE nombre ILIKE %s ORDER BY id", ('%' + filtro +*
