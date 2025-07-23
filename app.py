from flask import Flask, render_template, request, session, redirect
import sqlite3

app = Flask(__name__)
app.secret_key = 'tu_clave_secreta'

def get_db_connection():
    conn = sqlite3.connect('cobros.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/inicio')
def inicio():
    if 'usuario' not in session:
        return redirect('/')

    filtro = request.args.get('filtro', '').strip()
    conn = get_db_connection()
    cursor = conn.cursor()

    if filtro:
        cursor.execute("SELECT * FROM clientes WHERE nombre LIKE ?", ('%' + filtro + '%',))
    else:
        cursor.execute("SELECT * FROM clientes")

    clientes = cursor.fetchall()
    conn.close()

    return render_template('inicio.html', clientes=clientes, filtro=filtro)

# ... otras rutas ...
