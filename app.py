from flask import Flask, render_template, request, session, redirect
import sqlite3

app = Flask(__name__)
app.secret_key = 'tu_clave_secreta'  # Cambia por una clave segura

def get_db_connection():
    conn = sqlite3.connect('cobros.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        clave = request.form['clave']
        if usuario == 'admin' and clave == 'admin':  # Login fijo para ejemplo
            session['usuario'] = usuario
            return redirect('/inicio')
        else:
            return render_template('login.html', error='Usuario o clave incorrecta')
    return render_template('login.html')

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

@app.route('/logout')
def logout():
    session.pop('usuario', None)
    return redirect('/')

if __name__ == '__main__':
    app.run(debug=True)
