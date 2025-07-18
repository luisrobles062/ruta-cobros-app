from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
import os

app = Flask(__name__)
app.secret_key = 'secreto_super_seguro'  # Cambiar por algo más fuerte en producción

# Ruta absoluta para la base de datos
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(BASE_DIR, 'cobros.db')


# === RUTA LOGIN ===
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        contraseña = request.form['contraseña']

        # Login básico por defecto
        if usuario == 'admin' and contraseña == 'admin123':
            session['usuario'] = usuario
            return redirect('/inicio')
        else:
            flash('Usuario o contraseña incorrectos')
            return redirect('/')
    return render_template('login.html')


# === RUTA PRINCIPAL PROTEGIDA ===
@app.route('/inicio')
def inicio():
    if 'usuario' in session:
        return render_template('inicio.html')  # Asegúrate de tener esta plantilla
    else:
        return redirect('/')


# === RUTA CERRAR SESIÓN ===
@app.route('/logout')
def logout():
    session.pop('usuario', None)
    return redirect('/')


# === EJECUCIÓN LOCAL ===
if __name__ == '__main__':
    app.run(debug=True)
