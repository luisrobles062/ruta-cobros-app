import psycopg2
import os

# URL de conexión de PostgreSQL (Render la define así)
DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    # Puedes pegar la cadena directamente si prefieres
    DATABASE_URL = 'postgresql://cobros_user:qf5rdhUywTUKi0qRFvtK2TQrgvaHtBjQ@dpg-d21or4emcj7s73eqk1j0-a.oregon-postgres.render.com/cobros_db_apyt'

# Conectar a PostgreSQL
conn = psycopg2.connect(DATABASE_URL, sslmode='require')
cursor = conn.cursor()

# Consultar todas las tablas existentes
cursor.execute("""
    SELECT table_name 
    FROM information_schema.tables 
    WHERE table_schema = 'public'
""")
tablas = cursor.fetchall()

print("\nTablas en la base de datos PostgreSQL:")
for tabla in tablas:
    print(f"- {tabla[0]}")

# Si existe 'clientes', mostrar su estructura
if ('clientes',) in tablas:
    print("\nEstructura de la tabla 'clientes':")
    cursor.execute("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'clientes'
    """)
    columnas = cursor.fetchall()
    for col in columnas:
        print(f"{col[0]} ({col[1]})")

conn.close()
