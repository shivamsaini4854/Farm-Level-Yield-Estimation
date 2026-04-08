from flask import Flask, render_template, request
from fetch_weather import get_agricultural_weather

app = Flask(__name__)

# We added 'POST' to allow the website to send data (button clicks) to the server
@app.route('/', methods=['GET', 'POST'])
def home():
    weather_data = None
    
    if request.method == 'POST':
        # When the user clicks the button, fetch the live data for Farmer 1
        weather_data = get_agricultural_weather(30.0289, 77.1462, 1)
        
    # Pass the weather data to the HTML page
    return render_template('index.html', weather=weather_data)

if __name__ == '__main__':
    app.run(debug=True)