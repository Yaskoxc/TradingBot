import alpaca_trade_api as tradeapi
import os
import requests
import time
import json
import logging
from plyer import notification
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, render_template, jsonify, request
from threading import Thread
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.offline import plot
from plotly.subplots import make_subplots

# Configuration
CONFIG_FILE = 'config.json'
DEFAULT_CONFIG = {
    "alpaca_api_key": "PK66CJ8R0CHOKOJK89YS",  # À remplacer par des variables d'environnement!
    "alpaca_api_secret": "4D2Wc10XtQyiq75JTJIVeLwY8yygqMKBdhLZpEZT",
    "email_user": "karima.ecomerce@gmail.com",
    "email_pass": "Kima91@@",
    "email_receiver": "zeymaty56@gmail.com",
    "discord_webhook": "https://discord.com/api/webhooks/1329729401738235905/lVXSpQ5pLUcE4LiXOlAiFSjsydbW4zTlejqShZ57UqM74u7EFeT_BO9YMXV57AIRn-Tu",
    "symbols": ['AAPL', 'MSFT', 'GOOG', 'AMZN', 'TSLA'],
    "rsi_period": 14,
    "rsi_overbought": 70,
    "rsi_oversold": 30,
    "bollinger_period": 20,
    "bollinger_std": 2,
    "period": '5d',
    "interval": '1m',
    "notification_types": ["email", "desktop", "discord"],  # Ajout de "discord" par défaut
    "alpaca_paper": True,
    "trade_percentage": 0.01,  # 1% du capital par trade
    "stop_loss_percentage": 0.02,
    "take_profit_percentage": 0.03,
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
        config.update({k: v for k, v in DEFAULT_CONFIG.items() if k not in config})
        return config
    else:
        return DEFAULT_CONFIG

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

CONFIG = load_config()

# Logging configuration
logging.basicConfig(
    filename='trade_bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Flask app
app = Flask(__name__)
alerts = []
stock_data = {} # Stocker les données des actions analysées

def log_action(message):
    logging.info(message)
    print(message)

# Alpaca API setup (moved to function to handle updates)
def initialize_alpaca_api():
    global api
    API_KEY = CONFIG["alpaca_api_key"]
    API_SECRET = CONFIG["alpaca_api_secret"]
    BASE_URL = "https://paper-api.alpaca.markets" if CONFIG["alpaca_paper"] else "https://api.alpaca.markets"
    try:
      api = tradeapi.REST(API_KEY, API_SECRET, BASE_URL, api_version='v2')
      log_action("API Alpaca initialisée avec succès.")
    except Exception as e:
      log_action(f"Erreur lors de l'initialisation de l'API Alpaca : {e}")
      api = None

initialize_alpaca_api() # Initialisation de l'API au démarrage

# Helper functions
def log_action(message):
    logging.info(message)
    print(message)

def send_notification(title, message):
    if "desktop" in CONFIG.get("notification_types", []):
        notification.notify(
            title=title,
            message=message,
            app_name="Trade Bot",
            timeout=10
        )

def send_email(subject, body):
    if "email" in CONFIG.get("notification_types", []) and all([CONFIG["email_user"], CONFIG["email_pass"], CONFIG["email_receiver"]]):
        try:
            msg = MIMEMultipart()
            msg['From'] = CONFIG["email_user"]
            msg['To'] = CONFIG["email_receiver"]
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain'))
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(CONFIG["email_user"], CONFIG["email_pass"])
            server.send_message(msg)
            server.quit()
            log_action(f"Email envoyé avec succès: {subject}")
        except Exception as e:
            log_action(f"Erreur d'envoi d'email: {e}")

def send_discord_message(message):
    if "discord" in CONFIG.get("notification_types", []) and CONFIG.get("discord_webhook"):
        data = {"content": message}
        try:
            response = requests.post(CONFIG["discord_webhook"], json=data)
            response.raise_for_status()
            log_action(f"Discord message sent successfully: {message}")
        except requests.exceptions.RequestException as e:
            log_action(f"Error sending Discord message: {e}")

# Stock analysis class
class Stock:
    def __init__(self, symbol):
        self.symbol = symbol
        self.data = pd.DataFrame()

    def get_data(self):
        try:
            stock = yf.Ticker(self.symbol)
            self.data = stock.history(period=CONFIG["period"], interval=CONFIG["interval"])
            if self.data.empty:
                log_action(f"Aucune donnée disponible pour {self.symbol}.")
            return self.data
        except Exception as e:
            log_action(f"Erreur lors de la récupération des données pour {self.symbol}: {e}")
            return pd.DataFrame()

    def calculate_bollinger_bands(self, period, std_dev):
        if self.data.empty:
            return None, None, None
        sma = self.data['Close'].rolling(window=period).mean()
        std = self.data['Close'].rolling(window=period).std()
        upper_band = sma + (std_dev * std)
        lower_band = sma - (std_dev * std)
        return sma, upper_band, lower_band

    def calculate_rsi(self, period):
        if self.data.empty:
            return None
        delta = self.data['Close'].diff(1)
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def create_plot(self):
       if self.data.empty:
           return None
       sma, upper_band, lower_band = self.calculate_bollinger_bands(CONFIG["bollinger_period"], CONFIG["bollinger_std"])
       rsi = self.calculate_rsi(CONFIG["rsi_period"])

       # Créez une figure avec deux subplots (un pour le prix, l'autre pour le RSI)
       fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.1,
                           row_width=[0.2, 0.7])

       # Ajout du candlestick chart et des bandes de Bollinger
       fig.add_trace(go.Candlestick(x=self.data.index,
                                    open=self.data['Open'],
                                    high=self.data['High'],
                                    low=self.data['Low'],
                                    close=self.data['Close'], name=f"{self.symbol} Price"), row=1, col=1)
       fig.add_trace(go.Scatter(x=self.data.index, y=sma, mode='lines', name='SMA'), row=1, col=1)
       fig.add_trace(go.Scatter(x=self.data.index, y=upper_band, mode='lines', name='Upper Bollinger Band'), row=1, col=1)
       fig.add_trace(go.Scatter(x=self.data.index, y=lower_band, mode='lines', name='Lower Bollinger Band'), row=1, col=1)

       # Ajout du RSI
       fig.add_trace(go.Scatter(x=self.data.index, y=rsi, mode='lines', name="RSI"), row=2, col=1)
       fig.update_layout(title=f'Analyse de {self.symbol}', yaxis_title='Price', yaxis2_title='RSI')
       fig.update_xaxes(title_text='Date', row=2, col=1)  # Assurez-vous que l'axe des abscisses est sur le subplot inférieur

       return plot(fig, output_type='div')
    def analyze(self):
        self.get_data()
        if self.data.empty:
            log_action(f"{self.symbol}: Pas assez de données pour analyser.")
            return 'HOLD', 0, None, None, {}

        sma, upper_band, lower_band = self.calculate_bollinger_bands(CONFIG["bollinger_period"], CONFIG["bollinger_std"])
        rsi = self.calculate_rsi(CONFIG["rsi_period"])
        last_price = self.data['Close'].iloc[-1]
        decision = 'HOLD'
        log_action(f"{self.symbol}: Dernier prix: {last_price:.2f}, RSI: {rsi.iloc[-1]:.2f}, Bollinger: ({lower_band.iloc[-1]:.2f}, {upper_band.iloc[-1]:.2f})")

        if last_price < lower_band.iloc[-1] and rsi.iloc[-1] < CONFIG["rsi_oversold"]:
            decision = 'BUY'
            log_action(f"{self.symbol}: Signal d'achat détecté.")
        elif last_price > upper_band.iloc[-1] and rsi.iloc[-1] > CONFIG["rsi_overbought"]:
            decision = 'SELL'
            log_action(f"{self.symbol}: Signal de vente détecté.")

        plot_div = self.create_plot()
        # Calculer le pourcentage de variation depuis la veille
        previous_close = self.data['Close'].iloc[-2] if len(self.data) > 1 else last_price
        percentage_change = ((last_price - previous_close) / previous_close) * 100

        # Préparer les données à renvoyer au frontend
        additional_data = {
            'last_price': last_price,
            'percentage_change': percentage_change,
            'rsi': rsi.iloc[-1],
            'upper_bollinger': upper_band.iloc[-1],
            'lower_bollinger': lower_band.iloc[-1]
        }

        return decision, last_price, plot_div, self.data, additional_data

# Trading functions
def place_order(symbol, quantity, side, order_type='market', time_in_force='gtc', stop_loss=None, take_profit=None):
    try:
        if api is None:
          raise Exception("L'API Alpaca n'est pas initialisée. Veuillez vérifier la configuration.")
        order = api.submit_order(
            symbol=symbol,
            qty=quantity,
            side=side,
            type=order_type,
            time_in_force=time_in_force,
            stop_loss=stop_loss,
            take_profit=take_profit
        )
        log_action(f"Ordre {order_type} placé avec succès: {order}, quantity: {quantity}, side: {side}, stop_loss: {stop_loss}, take_profit: {take_profit}")
        return order
    except Exception as e:
        log_action(f"Erreur lors de la soumission de l'ordre: {e}")
        return None

def get_positions():
    try:
        if api is None:
          raise Exception("L'API Alpaca n'est pas initialisée. Veuillez vérifier la configuration.")
        positions = api.list_positions()
        return positions
    except Exception as e:
        log_action(f"Erreur lors de la récupération des positions: {e}")
        return []

def get_account():
    try:
        if api is None:
          raise Exception("L'API Alpaca n'est pas initialisée. Veuillez vérifier la configuration.")
        account = api.get_account()
        return account
    except Exception as e:
        log_action(f"Erreur lors de la récupération des informations de compte: {e}")
        return None

# Main analysis loop
def analyze_all_stocks():
    global alerts, stock_data
    account = get_account()
    if account is None:
        log_action("Impossible de récupérer les informations du compte.")
        return

    cash = float(account.cash)
    log_action(f"Solde disponible: {cash:.2f}")
    #stock_data = {}  # Réinitialiser les données des actions

    for symbol in CONFIG.get('symbols', []):
        stock = Stock(symbol)
        decision, last_price, plot_div, data, additional_data = stock.analyze()

        # Stocker les données pour l'affichage
        stock_data[symbol] = {
            'symbol': symbol,
            'decision': decision,
            'last_price': last_price,
            'plot': plot_div,
            'percentage_change': additional_data['percentage_change'],
            'rsi': additional_data['rsi'],
            'upper_bollinger': additional_data['upper_bollinger'],
            'lower_bollinger': additional_data['lower_bollinger']
        }

        if decision in ['BUY', 'SELL']:
            alert_msg = f"Signal: {decision} pour {symbol} à {last_price}"
            send_notification(f"Signal: {decision}", alert_msg)
            send_email(f"Signal: {decision}", alert_msg)
            send_discord_message(alert_msg)
            alerts.append({
                "symbol": symbol,
                "decision": decision,
                "last_price": last_price,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            })

            # Example of order placement
            if last_price > 0:
                quantity = int((cash * CONFIG["trade_percentage"]) / last_price) if cash > 0 else 0
                if quantity > 0:
                    try:
                        stop_loss_price = last_price * (1 - CONFIG["stop_loss_percentage"])
                        take_profit_price = last_price * (1 + CONFIG["take_profit_percentage"])
                        if decision == 'BUY':
                            order = place_order(symbol, quantity, 'buy',
                                                stop_loss={'stop_price': stop_loss_price},
                                                take_profit={'limit_price': take_profit_price})
                            if order:
                                log_action(f"Achat de {quantity} actions de {symbol} à {last_price:.2f}")
                        elif decision == 'SELL':
                            order = place_order(symbol, quantity, 'sell',
                                                stop_loss={'stop_price': stop_loss_price},
                                                take_profit={'limit_price': take_profit_price})
                            if order:
                                log_action(f"Vente de {quantity} actions de {symbol} à {last_price:.2f}")
                    except Exception as e:
                        log_action(f"Erreur lors de la soumission de l'ordre pour {symbol}: {e}")
                else:
                    log_action(f"Impossible de passer un ordre, quantite de 0 action pour {symbol}")

def run_scheduled_analysis():
    while True:
        analyze_all_stocks()
        time.sleep(10)

# Flask routes
@app.route('/')
def home():
    return render_template(
        'index.html',
        symbols=CONFIG.get('symbols', []),
        alerts=alerts,
        config=CONFIG,
        positions=get_positions(),
        account=get_account(),
        stock_data=stock_data # Passer les données des actions au template
    )

@app.route('/analyze/<symbol>')
def analyze(symbol):
    stock = Stock(symbol)
    decision, last_price, plot_div, data, additional_data = stock.analyze()

    if decision in ['BUY', 'SELL']:
        alert_msg = f"Signal: {decision} pour {symbol} à {last_price}"
        send_notification(f"Signal: {decision}", alert_msg)
        send_email(f"Signal: {decision}", alert_msg)
        send_discord_message(alert_msg)
        alerts.append({
            "symbol": symbol,
            "decision": decision,
            "last_price": last_price,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        })

        account = get_account()
        if account is None:
            log_action("Impossible de récupérer les informations du compte.")
            return jsonify({
                "symbol": symbol,
                "decision": decision,
                "last_price": last_price
            })

        cash = float(account.cash)
        if last_price > 0:
            quantity = int((cash * CONFIG["trade_percentage"]) / last_price) if cash > 0 else 0
            if quantity > 0:
                try:
                    stop_loss_price = last_price * (1 - CONFIG["stop_loss_percentage"])
                    take_profit_price = last_price * (1 + CONFIG["take_profit_percentage"])
                    if decision == 'BUY':
                        order = place_order(symbol, quantity, 'buy',
                                            stop_loss={'stop_price': stop_loss_price},
                                            take_profit={'limit_price': take_profit_price})
                        if order:
                            log_action(f"Achat de {quantity} actions de {symbol} à {last_price:.2f}")
                    elif decision == 'SELL':
                        order = place_order(symbol, quantity, 'sell',
                                            stop_loss={'stop_price': stop_loss_price},
                                            take_profit={'limit_price': take_profit_price})
                        if order:
                            log_action(f"Vente de {quantity} actions de {symbol} à {last_price:.2f}")
                except Exception as e:
                    log_action(f"Erreur lors de la soumission de l'ordre pour {symbol}: {e}")
            else:
                log_action(f"Impossible de passer un ordre, quantite de 0 action pour {symbol}")

    return jsonify({
        "symbol": symbol,
        "decision": decision,
        "last_price": last_price,
        "plot": plot_div,
        'percentage_change': additional_data['percentage_change'], # Inclure le pourcentage
        'rsi': additional_data['rsi'],
        'upper_bollinger': additional_data['upper_bollinger'],
        'lower_bollinger': additional_data['lower_bollinger']
    })

@app.route('/update_config', methods=['POST'])
def update_config():
    global CONFIG, api # Inclure api dans la portée globale
    new_config = request.get_json()
    if new_config:
        CONFIG.update(new_config)
        save_config(CONFIG)
        initialize_alpaca_api() # Réinitialiser l'API avec les nouvelles clés
        return jsonify({'message': 'Configuration updated'}), 200
    else:
        return jsonify({'error': 'No configuration data provided'}), 400

# Starting the app
if __name__ == '__main__':
    log_action("Démarrage du bot de trading.")
    analysis_thread = Thread(target=run_scheduled_analysis)
    analysis_thread.daemon = True
    analysis_thread.start()
    app.run(debug=True, use_reloader=False)