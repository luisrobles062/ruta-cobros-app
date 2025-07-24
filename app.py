from flask import Flask, render_template, request, session, redirect, url_for
import sqlite3

app = Flask(__name__)
app.secret_key = 'tu_clave_secreta'  # Cambia esto por algo seguro

def get_db_connection():
    conn = sqlite3.connect('cobros.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        clave = request.form['clave']
        if usuario == 'admin' and clave == 'admin':
            session['usuario'] = usuario
            return redirect(url_for('inicio'))
        else:
            return render_template('login.html', error='Usuario o clave incorrecta')
    return render_template('login.html')

@app.route('/inicio')
def inicio():
    if 'usuario' not in session:
        return redirect(url_for('login'))

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

@app.route('/nuevo', methods=['GET', 'POST'])
def nuevo():
    if 'usuario' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        nombre = request.form['nombre'].strip()
        fecha = request.form['fecha'].strip()
        monto = request.form['monto'].strip()
        deuda = request.form['deuda'].strip()

        if not nombre or not monto or not deuda:
            error = "Por favor completa los campos obligatorios (nombre, monto, deuda)."
            return render_template('nuevo.html', error=error, nombre=nombre, fecha=fecha, monto=monto, deuda=deuda)

        try:
            monto_val = float(monto)
            deuda_val = float(deuda)
        except ValueError:
            error = "Monto y deuda deben ser números válidos."
            return render_template('nuevo.html', error=error, nombre=nombre, fecha=fecha, monto=monto, deuda=deuda)

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT INTO clientes (nombre, fecha, monto, deuda) VALUES (?, ?, ?, ?)',
                       (nombre, fecha, monto_val, deuda_val))
        conn.commit()
        conn.close()

        return redirect(url_for('inicio'))

    return render_template('nuevo.html')

@app.route('/logout')
def logout():
    session.pop('usuario', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
