# app.py
# -*- coding: utf-8 -*-
import os
import hmac
import calendar
from datetime import date, datetime, timedelta
from urllib.parse import urlparse, parse_qsl
from decimal import Decimal, InvalidOperation
from functools import wraps
from zoneinfo import ZoneInfo

from flask import (
    Flask, render_template, render_template_string,
    request, redirect, url_for, flash, jsonify, session
)
import psycopg2


# ================== CONFIG BASES ==================

DATABASES = {
    "COBROS": {
        "USER": "COBROS",
        "PASSWORD": "COBROS 2025",
        "URL": "postgresql://neondb_owner:npg_DqyQpk4iBLh3@ep-still-water-adszkvnv-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require"
    },
    "DIURNA": {
        "USER": "DIURNA",
        "PASSWORD": "DIURNA2026",
        "URL": "postgresql://neondb_owner:npg_CwJqDX7z9AaO@ep-cold-meadow-acvlsfm5-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require"
    }
}


# ================== TZ app ==================
APP_TZ = ZoneInfo("America/Bogota")

def today_local():
    return datetime.now(APP_TZ).date()


# ================== Flask ==================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "secreto")


# ================== DB CONNECTION DINÁMICA ==================
def get_database_url():
    user = session.get("auth_user")
    if user in DATABASES:
        return DATABASES[user]["URL"]
    raise RuntimeError("Base no configurada.")


def get_connection():
    url = get_database_url()
    u = urlparse(url)
    params = dict(parse_qsl(u.query))

    dsn_parts = [
        f"dbname={u.path.lstrip('/')}",
        f"user={u.username}",
        f"password={u.password}",
        f"host={u.hostname}",
        f"port={u.port or 5432}",
        f"sslmode={params.get('sslmode','require')}",
    ]

    dsn = " ".join(dsn_parts)
    conn = psycopg2.connect(dsn)

    with conn.cursor() as cur:
        cur.execute("SET TIME ZONE 'America/Bogota';")

    return conn


# ================== AUTH ==================
def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("auth_ok"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    username = request.form.get("username")
    password = request.form.get("password")

    if username in DATABASES:
        if hmac.compare_digest(password, DATABASES[username]["PASSWORD"]):
            session["auth_ok"] = True
            session["auth_user"] = username
            return redirect(url_for("home"))

    flash("Credenciales incorrectas", "warning")
    return redirect(url_for("login"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ================== SCHEMA (SE EJECUTA POR BASE) ==================
MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS clientes (
  id SERIAL PRIMARY KEY,
  nombre TEXT NOT NULL,
  monto_prestado NUMERIC(12,2) NOT NULL DEFAULT 0,
  deuda_actual NUMERIC(12,2) NOT NULL DEFAULT 0,
  observaciones TEXT,
  fecha_prestamo DATE NOT NULL DEFAULT CURRENT_DATE,
  fecha_ultimo_pago DATE,
  archivado BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS pagos (
  id SERIAL PRIMARY KEY,
  cliente_id INTEGER REFERENCES clientes(id) ON DELETE CASCADE,
  monto NUMERIC(14,2) NOT NULL,
  fecha_pago DATE NOT NULL DEFAULT CURRENT_DATE,
  metodo TEXT,
  nota TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_pagos_cliente_fecha
ON pagos (cliente_id, fecha_pago);
"""

def init_schema():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(MIGRATION_SQL)
        conn.commit()


@app.before_request
def ensure_schema():
    if session.get("auth_ok"):
        try:
            init_schema()
        except:
            pass


# ================== HOME ==================
@app.route("/")
@login_required
def home():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, nombre, monto_prestado, deuda_actual
                FROM clientes
                WHERE archivado = FALSE AND deuda_actual > 0
                ORDER BY id DESC;
            """)
            clientes = cur.fetchall()

    return render_template("inicio.html", clientes=clientes)


# ================== NUEVO CLIENTE ==================
@app.route("/clientes/nuevo", methods=["GET", "POST"])
@login_required
def cliente_nuevo():
    if request.method == "GET":
        return render_template("nuevo.html")

    nombre = request.form.get("nombre")
    monto = float(request.form.get("monto_prestado"))

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO clientes (nombre, monto_prestado, deuda_actual)
                VALUES (%s, %s, %s);
            """, (nombre, monto, monto))
        conn.commit()

    return redirect(url_for("home"))


# ================== PAGOS ==================
@app.route("/pagos/nuevo", methods=["POST"])
@login_required
def pago_nuevo():
    cliente_id = request.form.get("cliente_id")
    monto = float(request.form.get("monto"))

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO pagos (cliente_id, monto)
                VALUES (%s, %s);
            """, (cliente_id, monto))

            cur.execute("""
                UPDATE clientes
                SET deuda_actual = GREATEST(0, deuda_actual - %s)
                WHERE id = %s;
            """, (monto, cliente_id))

        conn.commit()

    return redirect(url_for("home"))


# ================== MAIN ==================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
