from flask import Flask, render_template, request, redirect, session, url_for
import sqlite3

app = Flask(__name__)
app.secret_key = 'clave_secreta'

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
            return render_template('login.html', error='Credenciales incorrectas')
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

    conn = sqlite3.connect('cobros.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM clientes')
    clientes = c.fetchall()
    conn.close()
    return render_template('inicio.html', clientes=clientes)

# ---------- NUEVO CLIENTE ----------
@app.route('/nuevo', methods=['GET', 'POST'])
def nuevo_cliente():
    if 'usuario' not in session:
        return redirect('/')

    if request.method == 'POST':
        nombre = request.form['nombre']
        monto_prestado = float(request.form['monto_prestado'])
        fecha_inicio = request.form['fecha_inicio']
        observaciones = request.form.get('observaciones', '')
        deuda_actual = monto_prestado  # Puedes calcular rédito si quieres

        conn = sqlite3.connect('cobros.db')
        c = conn.cursor()
        c.execute('''
            INSERT INTO clientes (fecha_prestamo, nombre, monto_prestado, deuda_actual, observaciones)
            VALUES (?, ?, ?, ?, ?)
        ''', (fecha_inicio, nombre, monto_prestado, deuda_actual, observaciones))
        conn.commit()
        conn.close()

        return redirect('/inicio')
    
    return render_template('nuevo.html')

# ---------- EJECUCIÓN ----------
if __name__ == '__main__':
    app.run(debug=True)
