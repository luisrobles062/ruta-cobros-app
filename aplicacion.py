import os
from flask import Flask, render_template, request, redirect, url_for, session, flash

app = Flask(__name__)
app.secret_key = "clave_secreta"

@app.route("/")
def login():
    return render_template("login.html")

@app.route("/ingresar", methods=["POST"])
def ingresar():
    usuario = request.form['usuario']
    clave = request.form['clave']
    
    if usuario == "admin" and clave == "1234":
        session["usuario"] = usuario
        return redirect(url_for("inicio"))
    else:
        flash("Usuario o clave incorrecta")
        return redirect(url_for("login"))

@app.route("/inicio")
def inicio():
    if "usuario" in session:
        return f"Bienvenido, {session['usuario']}"
    else:
        return redirect(url_for("login"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
