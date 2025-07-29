import sqlite3

conn = sqlite3.connect('cobros.db')
cursor = conn.cursor()

# Mostrar tablas
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
print("Tablas encontradas:", cursor.fetchall())

# Mostrar estructura de la tabla clientes
cursor.execute("PRAGMA table_info(clientes);")
print("\nEstructura de la tabla 'clientes':")
for col in cursor.fetchall():
    print(col)

conn.close()
