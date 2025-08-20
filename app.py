from flask import Flask, render_template, request, redirect, url_for, session, flash
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'secreto'

# -------------------
# CONEXIÓN A NEON
# -------------------
conn = psycopg2.connect(
    "postgresql://neondb_owner:TU_CONTRASENA@ep-soft-bush-acv2a8v4-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require"
)
cursor = conn.cursor(cursor_factory=RealDictCursor)

# -------------------
# LOGIN
# -------------------
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        contrasena = request.form['contrasena']

        cursor.execute(
            "SELECT * FROM usuarios WHERE usuario=%s AND contrasena=%s",
            (usuario, contrasena)
        )
        user = cursor.fetchone()

        if user:
            session['usuario'] = usuario
            return redirect(url_for('inicio'))
        else:
            flash('Usuario o contraseña incorrectos')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# -------------------
# INICIO / CLIENTES
# -------------------
@app.route('/inicio', methods=['GET', 'POST'])
def inicio():
    if 'usuario' not in session:
        return redirect(url_for('login'))

    # Obtener clientes
    cursor.execute("SELECT * FROM clientes ORDER BY id ASC")
    clientes = cursor.fetchall()

    # Totales
    total_deuda = sum(c['deuda_actual'] for c in clientes)
    total_efectivo = 0  # temporal, sin funcionalidad de efectivo diario
    total_combinado = total_deuda + total_efectivo

    return render_template('inicio.html', 
                           clientes=clientes, 
                           total_deuda=total_deuda, 
                           total_efectivo=total_efectivo, 
                           total_combinado=total_combinado, 
                           datetime=datetime)

# -------------------
# REGISTRAR PAGO
# -------------------
@app.route('/pago/<int:cliente_id>', methods=['POST'])
def pago(cliente_id):
    if 'usuario' not in session:
        return redirect(url_for('login'))

    monto = request.form.get('monto', type=float)

    if monto and monto > 0:
        fecha_pago = datetime.now().date()
        cursor.execute(
            "INSERT INTO pagos (cliente_id, monto, fecha_pago) VALUES (%s, %s, %s)",
            (cliente_id, monto, fecha_pago)
        )
        # Actualizar deuda
        cursor.execute(
            "UPDATE clientes SET deuda_actual = deuda_actual - %s WHERE id = %s",
            (monto, cliente_id)
        )
        conn.commit()
        flash(f'Pago registrado correctamente: {monto}')
    else:
        flash('Monto inválido')

    return redirect(url_for('inicio'))

# -------------------
# EJECUTAR APP
# -------------------
if __name__ == '__main__':
    app.run(debug=True)
