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

# ================== TZ app ==================
APP_TZ = ZoneInfo(os.getenv("APP_TZ", "America/Bogota"))

def today_local() -> date:
    return datetime.now(APP_TZ).date()

# ================== Flask ==================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "secreto")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=(os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"),
)

# ========= Auth simple =========
AUTH_USERNAME = "COBROS"
AUTH_PASSWORD = "COBROS 2025"

def _verify_password(pwd: str) -> bool:
    return hmac.compare_digest(pwd, AUTH_PASSWORD)

def _is_safe_next(target: str) -> bool:
    if not target:
        return False
    u = urlparse(target)
    return not u.netloc and (u.path or "/") and not u.scheme

def login_required(fn):
    @wraps(fn)
    def _wrap(*args, **kwargs):
        if not session.get("auth_ok"):
            nxt = request.path if request.method == "GET" else None
            return redirect(url_for("login", next=nxt))
        return fn(*args, **kwargs)
    return _wrap

# ========= Conexión DB =========
RAW_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://neondb_owner:npg_DqyQpk4iBLh3@ep-still-water-adszkvnv-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require"
).strip()

def _sanitize_url(url: str) -> str:
    url = (url or "").strip().strip('\'"').strip()
    if not url:
        return url
    if "channel_binding=" in url:
        u = urlparse(url)
        params = dict(parse_qsl(u.query))
        params.pop("channel_binding", None)
        q = "&".join(f"{k}={v}" for k, v in params.items()) if params else ""
        url = u._replace(query=q).geturl()
    return url

DATABASE_URL = _sanitize_url(RAW_DATABASE_URL)

def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL no configurada.")
    u = urlparse(DATABASE_URL)
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
        cur.execute("SET TIME ZONE %s;", (os.getenv("DB_TZ", "America/Bogota"),))
    return conn

# ========= Utils =========
def parse_amount(txt: str) -> float:
    if txt is None:
        raise ValueError("empty")
    t = txt.strip()
    if not t:
        raise ValueError("empty")
    for ch in ["$", "€", "₡", "₲", "₵", "£", "¥", "₿", " "]:
        t = t.replace(ch, "")
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t and "." not in t:
        t = t.replace(",", ".")
    return float(t)

def money(n):
    try:
        return f"${float(n):,.2f}"
    except Exception:
        return n

def end_of_month(d: date) -> date:
    last = calendar.monthrange(d.year, d.month)[1]
    return d.replace(day=last)

# ========= (Aquí va todo tu MIGRATION_SQL, init_schema, rutas de clientes, pagos, efectivo, gastos, crecimiento, etc.) =========
# --- NO MODIFIQUÉ NADA DE LO QUE YA TENÍAS ---

# ======================= NUEVO: Proyección =======================
@app.get("/proyeccion")
@login_required
def proyeccion():
    """
    Proyección de cómo cerrará el mes, tomando el promedio diario de total_general
    (deuda + efectivo) y proyectándolo al último día del mes.
    """
    hoy = today_local()
    fin_mes = end_of_month(hoy)

    # Recolectar histórico diario
    historico = []
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT d::date,
                   COALESCE((
                     SELECT SUM(GREATEST(0, c.monto_prestado - COALESCE(p.total,0)))
                     FROM clientes c
                     LEFT JOIN (
                        SELECT cliente_id, SUM(monto) total
                        FROM pagos
                        WHERE fecha_pago <= d
                        GROUP BY cliente_id
                     ) p ON p.cliente_id=c.id
                     WHERE c.fecha_prestamo <= d
                   ),0) AS deuda,
                   COALESCE((
                     SELECT SUM(monto) FROM efectivo_diario e WHERE e.fecha = d
                   ),0) AS efectivo
            FROM generate_series(date_trunc('month', %s::date)::date, %s::date, interval '1 day') d
            ORDER BY d;
        """, (hoy, hoy))
        rows = cur.fetchall()
        for r in rows:
            total = float(r[1] or 0) + float(r[2] or 0)
            historico.append({"fecha": r[0].isoformat(), "deuda": float(r[1] or 0), "efectivo": float(r[2] or 0), "total": total})

    # Promedio diario y proyección
    dias_transcurridos = len(historico)
    promedio = sum(x["total"] for x in historico) / dias_transcurridos if dias_transcurridos > 0 else 0
    proyeccion_total = promedio * calendar.monthrange(hoy.year, hoy.month)[1]

    html = """
    <!doctype html>
    <html lang="es">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Proyección mensual</title>
      <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
      <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    </head>
    <body class="bg-light">
    <div class="container mt-3">
      <h3>Proyección de cierre de mes</h3>
      <p>Hoy: {{ hoy }} | Fin de mes: {{ fin_mes }}</p>
      <p>Promedio diario: <strong>{{ money(promedio) }}</strong></p>
      <p>Proyección al cierre: <strong>{{ money(proyeccion_total) }}</strong></p>
      <canvas id="chart" height="100"></canvas>
      <a class="btn btn-secondary btn-sm mt-3" href="{{ url_for('home') }}">Volver</a>
    </div>
    <script>
      const ctx = document.getElementById('chart').getContext('2d');
      const data = {
        labels: {{ labels|safe }},
        datasets: [{
          label: 'Total diario',
          data: {{ totals|safe }},
          borderColor: 'blue',
          fill: false,
          tension: 0.1
        }]
      };
      new Chart(ctx, { type: 'line', data: data });
    </script>
    </body>
    </html>
    """
    return render_template_string(
        html,
        hoy=hoy.isoformat(),
        fin_mes=fin_mes.isoformat(),
        promedio=promedio,
        proyeccion_total=proyeccion_total,
        labels=[x["fecha"] for x in historico],
        totals=[x["total"] for x in historico],
        money=money
    )

# -------- Main --------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
