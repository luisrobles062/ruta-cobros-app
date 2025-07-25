from flask import render_template, redirect, session
import psycopg2
import psycopg2.extras

def get_db_connection():
    return psycopg2.connect(
        host="dpg-d21or4emcj7s73eqk1j0-a.oregon-postgres.render.com",
        database="cobros_db_apyt",
        user="cobros_user",
        password="qf5rdhUywTUKi0qRFvtK2TQrgvaHtBjQ"
    )

@app.route('/pagos')
def pagos():
    if 'usuario' not in session:
        return redirect('/')

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("""
        SELECT pagos.id, clientes.nombre, pagos.monto, pagos.fecha
        FROM pagos
        JOIN clientes ON pagos.cliente_id = clientes.id
        ORDER BY pagos.fecha DESC
    """)
    pagos = cur.fetchall()
    conn.close()

    return render_template('pagos.html', pagos=pagos)


@app.route('/pagos_cliente/<int:cliente_id>')
def pagos_cliente(cliente_id):
    if 'usuario' not in session:
        return redirect('/')

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("""
        SELECT pagos.id, clientes.nombre, pagos.monto, pagos.fecha
        FROM pagos
        JOIN clientes ON pagos.cliente_id = clientes.id
        WHERE clientes.id = %s
        ORDER BY pagos.fecha DESC
    """, (cliente_id,))
    pagos = cur.fetchall()
    conn.close()

    return render_template('pagos.html', pagos=pagos)
