import os
from typing import Any

import requests
from flask import Flask, render_template

app = Flask(__name__)

STEAM_API_KEY = os.environ.get("STEAM_API_KEY", "")
STEAM_USER_ID = os.environ.get("STEAM_USER_ID", "76561198421708463")
REQUEST_TIMEOUT_SECONDS = 15


def _safe_get_json(url: str) -> dict[str, Any]:
    response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def get_wishlist_app_ids(api_key: str, steam_id: str) -> list[int]:
    url = (
        "https://api.steampowered.com/IWishlistService/GetWishlist/v1/"
        f"?key={api_key}&steamid={steam_id}"
    )
    data = _safe_get_json(url)
    items = data.get("response", {}).get("items", [])

    app_ids: list[int] = []
    for item in items:
        appid = item.get("appid")
        if isinstance(appid, int):
            app_ids.append(appid)
    return app_ids


def get_app_name(api_key: str, app_id: int) -> str:
    url = (
        "https://api.steampowered.com/ICommunityService/GetApps/v1/"
        f"?key={api_key}&appids[0]={app_id}"
    )
    data = _safe_get_json(url)
    apps = data.get("response", {}).get("apps", [])
    if apps and isinstance(apps[0], dict):
        return apps[0].get("name") or f"App {app_id}"
    return f"App {app_id}"


def get_latest_news(api_key: str, app_id: int) -> dict[str, Any]:
    url = (
        "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
        f"?key={api_key}&appid={app_id}"
    )
    data = _safe_get_json(url)
    items = data.get("appnews", {}).get("newsitems", [])

    if not items:
        return {
            "title": "No news yet",
            "image_url": f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/header.jpg",
            "url": f"https://store.steampowered.com/app/{app_id}",
            "is_playtest": False,
        }

    selected_item = items[0]
    is_playtest = False

    for item in items:
        title = str(item.get("title") or "")
        contents = str(item.get("contents") or "")
        if "playtest" in f"{title} {contents}".lower():
            selected_item = item
            is_playtest = True
            break

    image_url = f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/header.jpg"
    return {
        "title": selected_item.get("title") or "Untitled news",
        "image_url": image_url,
        "url": selected_item.get("url") or f"https://store.steampowered.com/app/{app_id}",
        "is_playtest": is_playtest,
    }


def build_game_cards(api_key: str, steam_id: str) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for app_id in get_wishlist_app_ids(api_key, steam_id):
        app_name = get_app_name(api_key, app_id)
        latest_news = get_latest_news(api_key, app_id)
        cards.append(
            {
                "app_id": str(app_id),
                "app_name": app_name,
                "news_title": latest_news["title"],
                "news_image": latest_news["image_url"],
                "news_url": latest_news["url"],
                "is_playtest": latest_news["is_playtest"],
                "store_url": f"https://store.steampowered.com/app/{app_id}",
            }
        )
    return cards


@app.route("/")
def index():
    cards: list[dict[str, Any]] = []
    error = None

    if not STEAM_API_KEY:
        error = "STEAM_API_KEY environment variable is not set."
        return render_template("index.html", cards=cards, error=error, steam_user_id=STEAM_USER_ID)

    try:
        cards = build_game_cards(STEAM_API_KEY, STEAM_USER_ID)
    except requests.RequestException as exc:
        error = f"Steam API request failed: {exc}"

    return render_template("index.html", cards=cards, error=error, steam_user_id=STEAM_USER_ID)


if __name__ == "__main__":
    app.run(debug=True)
