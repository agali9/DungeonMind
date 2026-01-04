from flask import Flask, request, render_template, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
import random
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

player_data = []

@app.route('/main_page')
def main_page():
    return render_template('main.html', players=player_data)

@app.route('/race')
def index():
    return render_template('Race.html')  

@app.route('/')
def start():
    return render_template('start.html')

@app.route('/receive_list', methods=['POST'])
def receive_list():
    global player_data
    player_data = request.json.get('players', [])
    return jsonify({"message": "Player data received", "data": player_data})


if __name__ == "__main__":
    app.run(debug=True)

