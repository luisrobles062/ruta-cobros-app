import sqlite3

conn = sqlite3.connect('cobros.db')
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS pagos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER NOT NULL,
    monto REAL NOT NULL,
    fecha TEXT NOT NULL,
    FOREIGN KEY (cliente_id) REFERENCES clientes(id)
)
''')

conn.commit()
conn.close()

print("✅ Tabla 'pagos' creada correctamente.")
