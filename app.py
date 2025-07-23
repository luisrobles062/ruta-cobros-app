from flask import Flask, render_template, request, redirect, session, url_for
import sqlite3

app = Flask(__name__)
app.secret_key = 'clave_secreta'

# Ruta de inicio de sesión
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        contraseña = request.form['contraseña']
        if usuario == 'admin' and contraseña == 'admin':
            session['usuario'] = usuario
            return redirect('/inicio')
        else:
            return render_template('login.html', mensaje='Credenciales incorrectas')
    return render_template('login.html')

# Cerrar sesión
@app.route('/logout')
def logout():
    session.pop('usuario', None)
    return redirect('/')

# Página principal con lista de clientes
@app.route('/inicio')
def inicio():
    if 'usuario' not in session:
        return redirect('/')
    
    conexion = sqlite3.connect('cobros.db')
    cursor = conexion.cursor()
    cursor.execute('SELECT id, nombre, monto, deuda_actual, fecha_inicio, Observaciones FROM clientes')
    clientes = cursor.fetchall()
    conexion.close()

    return render_template('inicio.html', clientes=clientes)

# Registrar nuevo cliente
@app.route('/nuevo', methods=['GET', 'POST'])
def nuevo_cliente():
    if request.method == 'POST':
        try:
            nombre = request.form['nombre']
            monto = float(request.form['monto'])  # Campo correcto según tu BD
            fecha_inicio = request.form['fecha_inicio']
            observaciones = request.form.get('observaciones', '')
            deuda_actual = monto  # Inicialmente igual al monto

            conexion = sqlite3.connect('cobros.db')
            cursor = conexion.cursor()
            cursor.execute('''
                INSERT INTO clientes (nombre, monto, deuda_actual, fecha_inicio, Observaciones)
                VALUES (?, ?, ?, ?, ?)
            ''', (nombre, monto, deuda_actual, fecha_inicio, observaciones))
            conexion.commit()
            conexion.close()
            return redirect(url_for('inicio'))
        except Exception as e:
            return f"❌ Error al guardar cliente: {str(e)}"
    
    return render_template('nuevo.html')

if __name__ == '__main__':
    app.run(debug=True)
