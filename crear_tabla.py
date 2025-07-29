import sqlite3

conn = sqlite3.connect('cobros.db')
cursor = conn.cursor()

# Eliminar la tabla antigua
cursor.execute("DROP TABLE IF EXISTS clientes")

# Crear la nueva tabla correcta
cursor.execute('''
CREATE TABLE clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT,
    nombre TEXT,
    monto_prestado REAL,
    porcentaje REAL,
    deuda_actual REAL,
    observaciones TEXT
)
''')

conn.commit()
conn.close()

print("✅ Tabla 'clientes' creada correctamente.")
