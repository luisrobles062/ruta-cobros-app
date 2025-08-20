from flask import Flask, render_template, request, redirect, url_for, flash, session
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'supersecreto123'

# Configuración de la base de datos Neon
DB_HOST = "ep-soft-bush-acv2a8v4-pooler.sa-east-1.aws.neon.tech"
DB_NAME = "neondb"
DB_USER = "neondb_owner"
DB_PASSWORD = "npg_3owpfIUOAT0a"
DB_PORT = 5432

def get_db_connection():
    conn = psycopg2.connect(
        host=DB_HOST,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        port=DB_PORT,
        sslmode='require'
    )
    return conn

# ----------- RUTAS -----------

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        clave = request.form['clave']
        if usuario == 'admin' and clave == 'admin':
            session['usuario'] = usuario
            return redirect(url_for('inicio'))
        else:
            flash('Usuario o contraseña incorrectos', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('usuario', None)
    return redirect(url_for('login'))

@app.route('/inicio')
def inicio():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM clientes ORDER BY id ASC;")
    clientes = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('inicio.html', clientes=clientes)

@app.route('/nuevo', methods=['GET', 'POST'])
def nuevo_cliente():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        nombre = request.form['nombre']
        monto = float(request.form['monto'])
        porcentaje = float(request.form['porcentaje'])
        deuda_actual = monto  # Inicialmente la deuda es el monto prestado
        fecha = datetime.now().strftime("%Y-%m-%d")
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO clientes (fecha, nombre, monto_prestado, porcentaje, deuda_actual)
            VALUES (%s, %s, %s, %s, %s)
        """, (fecha, nombre, monto, porcentaje, deuda_actual))
        conn.commit()
        cur.close()
        conn.close()
        flash('Cliente registrado correctamente', 'success')
        return redirect(url_for('inicio'))
    return render_template('nuevo_cliente.html')

@app.route('/pago/<int:cliente_id>', methods=['POST'])
def registrar_pago(cliente_id):
    if 'usuario' not in session:
        return redirect(url_for('login'))
    pago = float(request.form['pago'])
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Obtener deuda actual
    cur.execute("SELECT deuda_actual FROM clientes WHERE id = %s;", (cliente_id,))
    cliente = cur.fetchone()
    if not cliente:
        flash('Cliente no encontrado', 'error')
        cur.close()
        conn.close()
        return redirect(url_for('inicio'))
    
    nueva_deuda = cliente['deuda_actual'] - pago
    if nueva_deuda < 0:
        nueva_deuda = 0
    
    # Actualizar deuda
    cur.execute("UPDATE clientes SET deuda_actual = %s WHERE id = %s;", (nueva_deuda, cliente_id))
    
    # Registrar pago
    fecha_pago = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO pagos (cliente_id, monto, fecha) VALUES (%s, %s, %s);", (cliente_id, pago, fecha_pago))
    
    conn.commit()
    cur.close()
    conn.close()
    
    flash('Pago registrado correctamente', 'success')
    return redirect(url_for('inicio'))

# ----------- EJECUCIÓN -----------

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
