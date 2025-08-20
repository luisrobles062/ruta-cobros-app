from flask import Flask, render_template, request, redirect, url_for, flash
import psycopg2
import psycopg2.extras
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'secreto'

# Configuración de la base de datos Neon
DB_HOST = "ep-still-water-adszkvnv-pooler.c-2.us-east-1.aws.neon.tech"
DB_NAME = "neondb"
DB_USER = "neondb_owner"
DB_PASS = "npg_DqyQpk4iBLh3"
DB_PORT = "5432"

def get_db_connection():
    conn = psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        port=DB_PORT,
        sslmode='require'
    )
    return conn

# ----------- RUTAS -----------

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        usuario = request.form['usuario']
        contraseña = request.form['contraseña']
        if usuario == 'admin' and contraseña == 'admin':
            return redirect(url_for('inicio'))
        else:
            error = "Usuario o contraseña incorrectos"
    return render_template('login.html', error=error)

@app.route('/inicio')
def inicio():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT id, nombre, telefono, documento, fecha_registro FROM clientes ORDER BY id ASC;")
    clientes = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('inicio.html', clientes=clientes)

# Ruta para agregar clientes manualmente
@app.route('/nuevo', methods=['GET', 'POST'])
def nuevo():
    if request.method == 'POST':
        nombre = request.form['nombre']
        telefono = request.form['telefono']
        # Documento opcional
        documento = request.form.get('documento', 'N/A')
        fecha = datetime.now().date()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO clientes (nombre, telefono, documento, fecha_registro) VALUES (%s,%s,%s,%s)",
            (nombre, telefono, documento, fecha)
        )
        conn.commit()
        cur.close()
        conn.close()
        flash("Cliente agregado correctamente")
        return redirect(url_for('inicio'))
    return render_template('nuevo_cliente.html')

# ----------- EJECUCIÓN -----------

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
