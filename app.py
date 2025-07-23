from flask import Flask, render_template, request, redirect, session, url_for
import sqlite3
import os

app = Flask(__name__)
app.secret_key = 'clave_secreta'

DATABASE = 'cobros.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def login():
    return redirect(url_for('inicio'))  # Redirigir a la vista principal directamente por ahora

@app.route('/inicio')
def inicio():
    conn = get_db_connection()
    clientes = conn.execute('SELECT * FROM clientes').fetchall()
    conn.close()
    return render_template('inicio.html', clientes=clientes)

@app.route('/nuevo', methods=['GET', 'POST'])
def nuevo_cliente():
    if request.method == 'POST':
        nombre = request.form['nombre']
        monto_prestado = float(request.form['monto_prestado'])
        fecha_inicio = request.form['fecha_inicio']
        observaciones = request.form['observaciones']

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO clientes (nombre, monto_prestado, fecha_prestamo, deuda_actual, observaciones)
            VALUES (?, ?, ?, ?, ?)
        ''', (nombre, monto_prestado, fecha_inicio, monto_prestado, observaciones))
        conn.commit()
        conn.close()

        return redirect(url_for('inicio'))

    return render_template('nuevo.html')

if __name__ == '__main__':
    app.run(debug=True)
