from flask import Flask, render_template, request, redirect, session, url_for
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'clave_secreta'

DB_URL = 'postgresql://cobros_user:qf5rdhUywTUKi0qRFvtK2TQrgvaHtBjQ@dpg-d21or4emcj7s73eqk1j0-a.oregon-postgres.render.com/cobros_db_apyt'

def get_db_connection():
    conn = psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)
    return conn

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        contrasena = request.form['contrasena']
        if usuario == 'admin' and contrasena == 'admin':
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

    filtro = request.args.get('filtro', '')
    conn = get_db_connection()
    cur = conn.cursor()
    if filtro:
        cur.execute("SELECT * FROM clientes WHERE nombre ILIKE %s ORDER BY id", ('%' + filtro + '%',))
    else:
        cur.execute("SELECT * FROM clientes ORDER BY id")
    clientes = cur.fetchall()

    # Obtener pagos por cliente (sumar campo 'pago' de historial_pagos)
    pagos_dict = {}
    cur.execute("SELECT cliente_id, SUM(pago) as total_pagado FROM historial_pagos GROUP BY cliente_id")
    for fila in cur.fetchall():
        pagos_dict[fila['cliente_id']] = fila['total_pagado']

    conn.close()
    return render_template('inicio.html', clientes=clientes, filtro=filtro, pagos_dict=pagos_dict)

@app.route('/nuevo', methods=['GET', 'POST'])
def nuevo():
    if 'usuario' not in session:
        return redirect('/')
    if request.method == 'POST':
        nombre = request.form['nombre']
        fecha = request.form['fecha']
        monto = float(request.form['monto'])
        porcentaje = float(request.form['porcentaje'])
        deuda = monto + (monto * porcentaje / 100)
        observaciones = request.form['observaciones']

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO clientes (fecha, nombre, monto, porcentaje, deuda, observaciones)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (fecha, nombre, monto, porcentaje, deuda, observaciones))
        conn.commit()
        conn.close()
        return redirect('/inicio')
    return render_template('nuevo.html')

@app.route('/registrar_pago/<int:cliente_id>', methods=['POST'])
def registrar_pago(cliente_id):
    monto_pago = float(request.form['monto_pago'])

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO historial_pagos (cliente_id, pago, fecha_pago) VALUES (%s, %s, %s)",
                (cliente_id, monto_pago, datetime.now()))
    # Actualizar deuda restando el pago
    cur.execute("UPDATE clientes SET deuda = deuda - %s WHERE id = %s",
                (monto_pago, cliente_id))
    conn.commit()
    conn.close()
    return redirect('/inicio')

@app.route('/editar_cliente/<int:id>', methods=['GET', 'POST'])
def editar_cliente(id):
    if 'usuario' not in session:
        return redirect('/')

    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == 'POST':
        nombre = request.form['nombre']
        fecha = request.form['fecha']
        monto = float(request.form['monto'])
        porcentaje = float(request.form['porcentaje'])
        deuda = float(request.form['deuda'])
        observaciones = request.form['observaciones']

        cur.execute("""
            UPDATE clientes SET fecha=%s, nombre=%s, monto=%s, porcentaje=%s,
            deuda=%s, observaciones=%s WHERE id=%s
        """, (fecha, nombre, monto, porcentaje, deuda, observaciones, id))
        conn.commit()
        conn.close()
        return redirect('/inicio')

    cur.execute("SELECT * FROM clientes WHERE id = %s", (id,))
    cliente = cur.fetchone()
    conn.close()
    return render_template('editar_cliente.html', cliente=cliente)

@app.route('/editar_pago/<int:cliente_id>/<int:pago_id>', methods=['GET', 'POST'])
def editar_pago(cliente_id, pago_id):
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == 'POST':
        nuevo_monto = float(request.form['monto'])
        cur.execute("SELECT pago FROM historial_pagos WHERE id = %s", (pago_id,))
        anterior_monto = cur.fetchone()['pago']
        diferencia = nuevo_monto - anterior_monto

        cur.execute("UPDATE historial_pagos SET pago = %s WHERE id = %s", (nuevo_monto, pago_id))
        cur.execute("UPDATE clientes SET deuda = deuda - %s WHERE id = %s",
                    (diferencia, cliente_id))
        conn.commit()
        conn.close()
        return redirect('/inicio')

    cur.execute("SELECT * FROM historial_pagos WHERE id = %s", (pago_id,))
    pago = cur.fetchone()
    conn.close()
    return render_template('editar_pago.html', pago=pago, cliente_id=cliente_id)

@app.route('/eliminar_pago/<int:cliente_id>/<int:pago_id>', methods=['POST'])
def eliminar_pago(cliente_id, pago_id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT pago FROM historial_pagos WHERE id = %s", (pago_id,))
    monto = cur.fetchone()['pago']

    cur.execute("DELETE FROM historial_pagos WHERE id = %s", (pago_id,))
    cur.execute("UPDATE clientes SET deuda = deuda + %s WHERE id = %s",
                (monto, cliente_id))
    conn.commit()
    conn.close()
    return redirect('/inicio')

if __name__ == '__main__':
    app.run(debug=True)
