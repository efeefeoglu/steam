import os
import requests
import json
import re
from flask import Flask, render_template

app = Flask(__name__)

STEAM_API_KEY = os.environ.get('STEAM_API_KEY', '')

def get_steam_id(username):
    url = f"https://api.steampowered.com/ISteamUser/ResolveVanityURL/v0001/?key={STEAM_API_KEY}&vanityurl={username}"
    try:
        response = requests.get(url)
        data = response.json()
        if data['response']['success'] == 1:
            return data['response']['steamid']
    except Exception as e:
        print(f"Error fetching steam id: {e}")
    return None

def get_wishlist(steam_id):
    url = f"https://store.steampowered.com/wishlist/profiles/{steam_id}/wishlistdata/"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    try:
        # First try to get it directly, if that fails, try to parse the page
        response = requests.get(url, headers=headers)
        content = response.text

        try:
            data = json.loads(content)
            if isinstance(data, dict):
                return [(k, v.get('name')) for k, v in data.items() if isinstance(v, dict) and 'name' in v]
        except json.JSONDecodeError:
            pass

        # Try to parse from HTML if not directly JSON
        match = re.search(r'\"rgApps\":(\{.*?\})(?=,\"rgPackages\")', content)
        if match:
            data = json.loads(match.group(1))
            return [(k, v.get('name')) for k, v in data.items()]

    except Exception as e:
        print(f"Error fetching wishlist: {e}")
    return []

@app.route('/')
def index():
    games = []
    error = None

    if not STEAM_API_KEY:
        error = "STEAM_API_KEY environment variable is not set."
        return render_template('index.html', games=games, error=error)

    username = "efenkullah"
    steam_id = get_steam_id(username)

    if steam_id:
        games = get_wishlist(steam_id)
    else:
        error = f"Could not resolve Steam ID for user '{username}'. Make sure your API key is correct."

    return render_template('index.html', games=games, error=error, username=username)

if __name__ == '__main__':
    app.run(debug=True)
