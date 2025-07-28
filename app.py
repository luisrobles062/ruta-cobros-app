from flask import Flask, render_template, request, redirect, session, url_for
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'clave_secreta'

# Conexión a la base de datos PostgreSQL en Render
def get_db_connection():
    return psycopg2.connect(
        dbname='cobros_db_apyt',
        user='cobros_user',
        password='qf5rdhUywTUKi0qRFvtK2TQrgvaHtBjQ',
        host='dpg-d21or4emcj7s73eqk1j0-a.oregon-postgres.render.com',
        port='5432',
        cursor_factory=RealDictCursor
    )

# Ruta de inicio de sesión
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['usuario'] == 'admin' and request.form['contrasena'] == 'admin':
            session['usuario'] = request.form['usuario']
            return redirect('/inicio')
        else:
            return render_template('login.html', error='Credenciales incorrectas')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

# Vista principal de clientes
@app.route('/inicio')
def inicio():
    if 'usuario' not in session:
        return redirect('/')
    
    filtro = request.args.get('filtro', '')
    conn = get_db_connection()
    cur = conn.cursor()
    
    if filtro:
        cur.execute("SELECT * FROM clientes WHERE nombre ILIKE %s ORDER BY id DESC", (f'%{filtro}%',))
    else:
        cur.execute("SELECT * FROM clientes ORDER BY id DESC")
    
    clientes = cur.fetchall()
    
    cur.execute("SELECT * FROM pagos ORDER BY fecha DESC")
    pagos = cur.fetchall()
    
    conn.close()
    return render_template('inicio.html', clientes=clientes, pagos=pagos, filtro=filtro)

# Registrar nuevo cliente
@app.route('/nuevo', methods=['GET', 'POST'])
def nuevo_cliente():
    if 'usuario' not in session:
        return redirect('/')
    
    if request.method == 'POST':
        nombre = request.form['nombre']
        monto_prestado = float(request.form['monto_prestado'])
        porcentaje = float(request.form['porcentaje'])
        deuda_actual = monto_prestado + (monto_prestado * porcentaje / 100)
        fecha = datetime.now().strftime('%Y-%m-%d')

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO clientes (fecha, nombre, monto_prestado, porcentaje, deuda_actual)
            VALUES (%s, %s, %s, %s, %s)
        ''', (fecha, nombre, monto_prestado, porcentaje, deuda_actual))
        conn.commit()
        conn.close()

        return redirect('/inicio')
    return render_template('nuevo_cliente.html')

# Registrar un pago
@app.route('/pagar/<int:cliente_id>', methods=['POST'])
def pagar(cliente_id):
    monto = float(request.form['monto_pago'])
    fecha = datetime.now().strftime('%Y-%m-%d')

    conn = get_db_connection()
    cur = conn.cursor()

    # Registrar el pago en la tabla pagos
    cur.execute('''
        INSERT INTO pagos (cliente_id, fecha, monto)
        VALUES (%s, %s, %s)
    ''', (cliente_id, fecha, monto))

    # Actualizar la deuda del cliente
    cur.execute('''
        UPDATE clientes SET deuda_actual = deuda_actual - %s WHERE id = %s
    ''', (monto, cliente_id))

    conn.commit()
    conn.close()
    return redirect('/inicio')

# Crear tablas si no existen (opcional)
def crear_tablas():
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute('''
        CREATE TABLE IF NOT EXISTS clientes (
            id SERIAL PRIMARY KEY,
            fecha DATE,
            nombre TEXT,
            monto_prestado NUMERIC,
            porcentaje NUMERIC,
            deuda_actual NUMERIC
        );
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS pagos (
            id SERIAL PRIMARY KEY,
            cliente_id INTEGER REFERENCES clientes(id),
            fecha DATE,
            monto NUMERIC
        );
    ''')
    
    conn.commit()
    conn.close()

if __name__ == '__main__':
    crear_tablas()
    app.run(debug=True)
