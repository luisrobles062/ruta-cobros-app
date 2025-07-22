from flask import Flask, render_template, request, redirect, session
import sqlite3

app = Flask(__name__)
app.secret_key = 'clave_secreta'  # Puedes cambiar esto por otra clave

# Ruta de inicio de sesión
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


# Ruta de cierre de sesión
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


# Ruta para mostrar clientes al iniciar sesión
@app.route('/inicio')
def inicio():
    if not session.get('usuario'):
        return redirect('/')

    conn = sqlite3.connect('cobros.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM clientes ORDER BY nombre ASC")
    clientes = cursor.fetchall()

    conn.close()

    return render_template('inicio.html', clientes=clientes)


# Ruta para registrar un nuevo cliente
@app.route('/nuevo', methods=['GET', 'POST'])
def nuevo_cliente():
    if not session.get('usuario'):
        return redirect('/')

    if request.method == 'POST':
        nombre = request.form['nombre']
        deuda = float(request.form['deuda'])
        fecha_inicio = request.form['fecha_inicio']
        observaciones = request.form['observaciones']

        conn = sqlite3.connect('cobros.db')
        cursor = conn.cursor()
        cursor.execute("INSERT INTO clientes (nombre, deuda, fecha_inicio, observaciones) VALUES (?, ?, ?, ?)",
                       (nombre, deuda, fecha_inicio, observaciones))
        conn.commit()
        conn.close()
        return redirect('/inicio')

    return render_template('nuevo.html')


# Ruta para registrar un pago
@app.route('/pago', methods=['POST'])
def registrar_pago():
    if not session.get('usuario'):
        return redirect('/')

    cliente_id = request.form['cliente_id']
    monto = float(request.form['monto'])
    comentario = request.form.get('comentario', '')

    conn = sqlite3.connect('cobros.db')
    cursor = conn.cursor()

    # Restar el pago a la deuda
    cursor.execute("UPDATE clientes SET deuda = deuda - ? WHERE id = ?", (monto, cliente_id))

    # Registrar el pago en la tabla 'cobros'
    cursor.execute("INSERT INTO cobros (cliente_id, monto, comentario) VALUES (?, ?, ?)",
                   (cliente_id, monto, comentario))

    conn.commit()
    conn.close()

    return redirect('/inicio')


if __name__ == '__main__':
    app.run(debug=True)
