import os
import time
import threading
from flask import Flask

app = Flask(__name__)

# --- RUTA PRINCIPAL PARA PINGS (cron-job.org / Render) ---
@app.route('/')
def home():
    # Devuelve una respuesta ultra liviana para evitar errores de tamaño de salida
    return "OK", 200

# --- LÓGICA DEL BOT DE TRADING EN SEGUNDO PLANO ---
def bot_loop():
    print("Papertrading activo. Balance virtual: $1000.00")
    while True:
        try:
            # Aquí va tu lógica de análisis técnico / trading (e.g. estrategia ORB, lectura de velas, etc.)
            # print("Analizando mercado...")
            pass
        except Exception as e:
            print(f"Error en el ciclo del bot: {e}")
        
        # Intervalo entre revisiones (por ejemplo, cada 60 segundos)
        time.sleep(60)

# --- INICIALIZACIÓN DEL HILO SECUNDARIO ---
# Inicia el hilo del bot en segundo plano solo cuando no está en modo debug
threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
