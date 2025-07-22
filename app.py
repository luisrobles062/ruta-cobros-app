from flask import Flask, render_template, request, redirect, session, url_for
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'clave_secreta'

def get_db_connection():
    conn = sqlite3.connect('cobros.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        contraseña = request.form['contraseña']
        if usuario == 'admin' and contraseña == 'admin':
            session['usuario'] = usuario
            return redirect('/inicio')
        else:
            return render_template('login.html', error='Credenciales incorrectas')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('usuario', None)
    return redirect('/')

@app.route('/inicio')
def inicio():
    if 'usuario' not in session:
        return redirect('/')

    filtro = request.args.get('filtro', '').lower()
    conn = get_db_connection()
    clientes = conn.execute('SELECT * FROM clientes').fetchall()
    pagos = conn.execute('SELECT cliente_id, SUM(monto) as total_pagado FROM pagos GROUP BY cliente_id').fetchall()
    conn.close()

    pagos_dict = {p['cliente_id']: p['total_pagado'] for p in pagos}
    clientes_filtrados = []

    for c in clientes:
        if filtro in c['nombre'].lower():
            cliente = dict(c)
            cliente['deuda_actual'] = c['monto'] - pagos_dict.get(c['id'], 0)
            clientes_filtrados.append(cliente)

    return render_template('inicio.html', clientes=clientes_filtrados, filtro=filtro)

@app.route('/pago/<int:id>', methods=['POST'])
def registrar_pago(id):
    if 'usuario' not in session:
        return redirect('/')

    monto = float(request.form['monto'])
    fecha = datetime.now().strftime('%Y-%m-%d')

    conn = get_db_connection()
    conn.execute('INSERT INTO pagos (cliente_id, monto, fecha) VALUES (?, ?, ?)', (id, monto, fecha))
    conn.commit()
    conn.close()

    return redirect('/inicio')

@app.route('/pagos/<int:id>')
def ver_pagos(id):
    if 'usuario' not in session:
        return redirect('/')

    conn = get_db_connection()
    cliente = conn.execute('SELECT * FROM clientes WHERE id = ?', (id,)).fetchone()
    pagos = conn.execute('SELECT fecha, monto FROM pagos WHERE cliente_id = ? ORDER BY fecha DESC', (id,)).fetchall()
    conn.close()

    return render_template('clientes_de_pagos.html', cliente=cliente, pagos=pagos)

@app.route('/nuevo', methods=['GET', 'POST'])
def nuevo():
    if 'usuario' not in session:
        return redirect('/')

    if request.method == 'POST':
        nombre = request.form['nombre']
        monto = float(request.form['monto'])
        fecha = request.form['fecha']
        observaciones = request.form['observaciones']

        conn = get_db_connection()
        conn.execute('INSERT INTO clientes (nombre, monto, fecha, observaciones) VALUES (?, ?, ?, ?)',
                     (nombre, monto, fecha, observaciones))
        conn.commit()
        conn.close()
        return redirect('/inicio')

    return render_template('nuevo.html')

if __name__ == '__main__':
    app.run(debug=True)
