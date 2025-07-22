import sqlite3

# Conectarse a la base de datos
conn = sqlite3.connect('cobros.db')
cursor = conn.cursor()

# Mostrar todas las tablas
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tablas = cursor.fetchall()

print("\nTablas en la base de datos:")
for tabla in tablas:
    print(f"- {tabla[0]}")

# Si existe una tabla llamada clientes, mostrar sus columnas
if ('clientes',) in tablas:
    print("\nEstructura de la tabla 'clientes':")
    cursor.execute("PRAGMA table_info(clientes);")
    columnas = cursor.fetchall()
    for col in columnas:
        print(f"{col[1]} ({col[2]})")

conn.close()
