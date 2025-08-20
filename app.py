from flask import Flask, render_template, request, redirect, url_for, session, flash
import psycopg2
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'secreto'  # Cambiar por algo más seguro en producción

# Conexión a la base de datos usando variable de entorno
DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    raise ValueError("No se encontró la variable de entorno DATABASE_URL")

try:
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
except Exception as e:
    print("Error al conectar con la base de datos:", e)
    raise

# Ruta Login
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form.get('usuario')
        contrasena = request.form.get('contrasena')
        cur.execute("SELECT * FROM usuarios WHERE usuario=%s AND contrasena=%s", (usuario, contrasena))
        user = cur.fetchone()
        if user:
            session['usuario'] = usuario
            return redirect(url_for('inicio'))
        else:
            flash('Usuario o contraseña incorrectos')
    return render_template('login.html')

# Ruta principal
@app.route('/inicio', methods=['GET'])
def inicio():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    cur.execute("SELECT * FROM clientes ORDER BY id ASC")
    clientes = cur.fetchall()

    # Convertir resultados en diccionarios para Jinja2
    clientes_list = []
    for c in clientes:
        clientes_list.append({
            'id': c[0],
            'nombre': c[1],
            'telefono': c[2],
            'documento': c[3],
            'fecha_registro': c[4],
            'monto_prestado': c[5],
            'deuda_actual': c[6],
            'observacion': c[7]
        })

    return render_template('inicio.html', clientes=clientes_list, datetime=datetime)

# Ruta Logout
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    # Para desarrollo local
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)
