import os
import time
import json
import threading
from datetime import datetime, timezone
import pandas as pd
import ccxt
import requests
from dotenv import load_dotenv
from flask import Flask

load_dotenv()

# --- CONFIGURACIÓN DE FLASK ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot de Papertrading activo y funcionando.", 200

# --- CONFIGURACIÓN DE ESTRATEGIA Y PAPERTRADING ---
SYMBOL = "ETH/USDT"
TIMEFRAME_LTF = "5m"
TIMEFRAME_HTF = "1h"
EMA_HTF_PERIOD = 200

NY_SESSION_START_HOUR = 13  # 13:30 UTC
ORB_MINUTES = 60            # Rango ORB 60 minutos
RR_RATIO = 1.5              # Ratio Riesgo/Beneficio
VOL_MULT = 1.3              # Filtro de Volumen (>30% sobre SMA20)
RISK_PCT = 0.015            # Riesgo virtual del 1.5% por operación

INITIAL_VIRTUAL_BALANCE = 1000.0  # Balance inicial de prueba
STATE_FILE = "papertrade_state.json"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Inicialización PÚBLICA de Binance (No requiere API Keys para Papertrading)
exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
})

def send_telegram(message):
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        try:
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            print(f"Error enviando mensaje a Telegram: {e}")

# --- GESTIÓN DE ESTADO PERSISTENTE ---
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error cargando estado: {e}")
    return {
        "balance": INITIAL_VIRTUAL_BALANCE,
        "active_position": None,
        "last_trade_date": None,
        "trade_history": []
    }

def save_state(state):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=4)
    except Exception as e:
        print(f"Error guardando estado: {e}")

def fetch_data():
    ohlcv_5m = exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME_LTF, limit=100)
    df_5m = pd.DataFrame(ohlcv_5m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df_5m['datetime'] = pd.to_datetime(df_5m['timestamp'], unit='ms', utc=True)
    df_5m['vol_sma'] = df_5m['volume'].rolling(20).mean()

    ohlcv_1h = exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME_HTF, limit=300)
    df_1h = pd.DataFrame(ohlcv_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df_1h['ema200_1h'] = df_1h['close'].ewm(span=EMA_HTF_PERIOD, adjust=False).mean()

    latest_ema200 = df_1h['ema200_1h'].iloc[-1]
    return df_5m, latest_ema200

def get_ny_orb_range(df):
    now = datetime.now(timezone.utc)
    today_ny_start = datetime(now.year, now.month, now.day, NY_SESSION_START_HOUR, 30, tzinfo=timezone.utc)
    today_ny_end = today_ny_start + pd.Timedelta(minutes=ORB_MINUTES)
    
    orb_df = df[(df['datetime'] >= today_ny_start) & (df['datetime'] < today_ny_end)]
    if len(orb_df) > 0:
        high = orb_df['high'].max()
        low = orb_df['low'].min()
        midpoint = (high + low) / 2.0
        return high, low, midpoint, today_ny_end
    return None, None, None, None

def run_papertrading():
    state = load_state()
    send_telegram(f"📝 *MOTOR DE PAPERTRADING INICIADO*\n\n• Balance Virtual: ${state['balance']:.2f} USDT\n• Símbolo: {SYMBOL}\n• Estado: Monitoreando mercado público en tiempo real...")
    print(f"Papertrading activo. Balance virtual: ${state['balance']:.2f}")

    while True:
        try:
            now = datetime.now(timezone.utc)
            today_str = str(now.date())

            df_5m, ema200_1h = fetch_data()
            orb_high, orb_low, orb_mid, orb_end_time = get_ny_orb_range(df_5m)

            current_candle = df_5m.iloc[-1]
            last_candle = df_5m.iloc[-2]
            prev_candle = df_5m.iloc[-3]

            pos = state["active_position"]

            # --- 1. EVALUAR SALIDA DE POSICIÓN VIRTUAL ABIERTA ---
            if pos is not None:
                high_p = current_candle['high']
                low_p = current_candle['low']
                side = pos['side']
                entry = pos['entry']
                sl = pos['sl']
                tp = pos['tp']
                qty = pos['qty']

                closed = False
                pnl = 0.0
                result_str = ""

                if side == 'LONG':
                    if high_p >= tp:
                        pnl = (tp - entry) * qty
                        result_str = "🎯 TAKE PROFIT ALCANZADO (+1.5R)"
                        closed = True
                    elif low_p <= sl:
                        pnl = (sl - entry) * qty
                        result_str = "🛑 STOP LOSS ALCANZADO (-1.0R)"
                        closed = True

                elif side == 'SHORT':
                    if low_p <= tp:
                        pnl = (entry - tp) * qty
                        result_str = "🎯 TAKE PROFIT ALCANZADO (+1.5R)"
                        closed = True
                    elif high_p >= sl:
                        pnl = (entry - sl) * qty
                        result_str = "🛑 STOP LOSS ALCANZADO (-1.0R)"
                        closed = True

                if closed:
                    state["balance"] += pnl
                    state["trade_history"].append({
                        "date": today_str,
                        "side": side,
                        "pnl": pnl,
                        "final_balance": state["balance"]
                    })
                    
                    msg = (f"{result_str}\n\n"
                           f"• Símbolo: {SYMBOL}\n"
                           f"• Lado: {side}\n"
                           f"• PnL Virtual: ${pnl:+.2f} USDT\n"
                           f"• Nuevo Balance: ${state['balance']:.2f} USDT")
                    send_telegram(msg)
                    
                    state["active_position"] = None
                    save_state(state)

            # --- 2. BUSCAR NUEVA ENTRADA (MÁXIMO 1 OPERACIÓN POR DÍA) ---
            if state["active_position"] is None and orb_high and orb_low and now >= orb_end_time:
                if state["last_trade_date"] != today_str:
                    vol_ok = last_candle['volume'] > (last_candle['vol_sma'] * VOL_MULT)
                    current_price = last_candle['close']
                    
                    htf_bullish = current_price > ema200_1h
                    htf_bearish = current_price < ema200_1h

                    # ENTRADA LONG
                    if prev_candle['close'] > orb_high and last_candle['low'] <= orb_high and last_candle['close'] > orb_high and vol_ok and htf_bullish:
                        entry = current_price
                        sl = orb_mid
                        risk_dist = entry - sl
                        
                        if risk_dist > 0:
                            tp = entry + (risk_dist * RR_RATIO)
                            risk_amt = state["balance"] * RISK_PCT
                            qty = risk_amt / risk_dist

                            state["active_position"] = {
                                "side": "LONG", "entry": entry, "sl": sl, "tp": tp, "qty": qty
                            }
                            state["last_trade_date"] = today_str
                            save_state(state)

                            msg = (f"🟢 *NUEVA POSICIÓN VIRTUAL LONG*\n\n"
                                   f"• Entrada: ${entry:.2f}\n"
                                   f"• Stop Loss (50% ORB): ${sl:.2f}\n"
                                   f"• Take Profit (1:1.5): ${tp:.2f}\n"
                                   f"• Tamaño Posición: {qty:.4f} ETH\n"
                                   f"• Riesgo Virtual (1.5%): ${risk_amt:.2f} USDT")
                            send_telegram(msg)

                    # ENTRADA SHORT
                    elif prev_candle['close'] < orb_low and last_candle['high'] >= orb_low and last_candle['close'] < orb_low and vol_ok and htf_bearish:
                        entry = current_price
                        sl = orb_mid
                        risk_dist = sl - entry
                        
                        if risk_dist > 0:
                            tp = entry - (risk_dist * RR_RATIO)
                            risk_amt = state["balance"] * RISK_PCT
                            qty = risk_amt / risk_dist

                            state["active_position"] = {
                                "side": "SHORT", "entry": entry, "sl": sl, "tp": tp, "qty": qty
                            }
                            state["last_trade_date"] = today_str
                            save_state(state)

                            msg = (f"🔴 *NUEVA POSICIÓN VIRTUAL SHORT*\n\n"
                                   f"• Entrada: ${entry:.2f}\n"
                                   f"• Stop Loss (50% ORB): ${sl:.2f}\n"
                                   f"• Take Profit (1:1.5): ${tp:.2f}\n"
                                   f"• Tamaño Posición: {qty:.4f} ETH\n"
                                   f"• Riesgo Virtual (1.5%): ${risk_amt:.2f} USDT")
                            send_telegram(msg)

            time.sleep(15)

        except Exception as e:
            print(f"Error en ejecución: {e}")
            time.sleep(10)

# --- INICIALIZACIÓN AUTOMÁTICA DE HILOS ---
bot_thread = threading.Thread(target=run_papertrading, daemon=True)
bot_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
