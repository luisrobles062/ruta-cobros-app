from flask import Flask, render_template

app = Flask(__name__)

@app.route('/')
def home():
    return '<h1>¡Ruta de Cobros funcionando correctamente!</h1>'

if __name__ == '__main__':
    app.run(debug=True)
