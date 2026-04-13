import os
from typing import Any

import psycopg
import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

STEAM_API_KEY = os.environ.get("STEAM_API_KEY")
STEAM_USER_ID = os.environ.get("STEAM_USER_ID")
DATABASE_URL = os.environ.get("DATABASE_URL")
REQUEST_TIMEOUT_SECONDS = 15
ALLOWED_STATUSES = {
    "released",
    "demo_played",
    "playtest_applied",
    "playtest_played",
}


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


def get_games_from_db(app_ids: list[int]) -> dict[int, dict[str, str]]:
    if not app_ids:
        return {}

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, status FROM games WHERE id = ANY(%s)",
                (app_ids,),
            )
            rows = cur.fetchall()

    games: dict[int, dict[str, str]] = {}
    for row in rows:
        game_id, name, status = row
        if isinstance(game_id, int):
            games[game_id] = {
                "name": name or f"App {game_id}",
                "status": status or "wishlisted",
            }
    return games


def save_new_games(new_games: list[tuple[int, str]]) -> None:
    if not new_games:
        return

    records = [(game_id, game_name, "wishlisted") for game_id, game_name in new_games]
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO games (id, name, status)
                VALUES (%s, %s, %s)
                """,
                records,
            )
        conn.commit()


def update_game_status(app_id: int, status: str) -> bool:
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE games SET status = %s WHERE id = %s",
                (status, app_id),
            )
            updated = cur.rowcount > 0
        conn.commit()
    return updated


def build_game_cards(api_key: str, steam_id: str) -> list[dict[str, Any]]:
    wishlist_app_ids = get_wishlist_app_ids(api_key, steam_id)
    games_by_id = get_games_from_db(wishlist_app_ids)

    new_games: list[tuple[int, str]] = []
    for app_id in wishlist_app_ids:
        if app_id not in games_by_id:
            app_name = get_app_name(api_key, app_id)
            games_by_id[app_id] = {"name": app_name, "status": "wishlisted"}
            new_games.append((app_id, app_name))

    save_new_games(new_games)

    cards: list[dict[str, Any]] = []
    for app_id in wishlist_app_ids:
        app_name = games_by_id.get(app_id, {}).get("name", f"App {app_id}")
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
                "status": games_by_id.get(app_id, {}).get("status", "wishlisted"),
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


@app.route("/status/<int:app_id>", methods=["POST"])
def set_status(app_id: int):
    payload = request.get_json(silent=True) or {}
    status = str(payload.get("status") or "").strip().lower()

    if status not in ALLOWED_STATUSES:
        return jsonify({"ok": False, "error": "Invalid status"}), 400

    updated = update_game_status(app_id, status)
    if not updated:
        return jsonify({"ok": False, "error": "Game not found"}), 404

    return jsonify({"ok": True, "app_id": app_id, "status": status})


if __name__ == "__main__":
    app.run(debug=True)
