"""Shared Steam pieces: app address parsing and the public lookups.
Registers no counter type itself; the steam_*.py files do.

Two routes, neither needing a key: GetNumberOfCurrentPlayers on the Web
API for the live player count, and the store's appdetails for the game's
name. The store answers about 200 requests per five minutes per address,
so a counter is capped at one fetch every five minutes."""

import re
import urllib.parse

from providers.base import CounterError, HttpError, http_json, parse_url

PLAYERS_API = "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"
DETAILS_API = "https://store.steampowered.com/api/appdetails"
STORE_HOSTS = ("store.steampowered.com", "steamcommunity.com", "www.steamcommunity.com")
APP_ID_RE = re.compile(r"^[1-9][0-9]{0,8}$")

BRAND_COLOR = ""   # none: the logo is drawn in the bar's own colour, white on a dark theme, as Steam draws it
RATE_NOTE = "the store answers about 200 requests per 5 minutes per address"
HELP = "a Steam game is its store URL (store.steampowered.com/app/<id>/…) or its app id"


def normalize_app(raw):
    """store.steampowered.com/app/<id>/<slug>, steamcommunity.com/app/<id>
    or a bare app id → the app id as a string. A bare id has at most nine
    digits, so an eleven-character YouTube video id never reads as one."""
    text = str(raw or "").strip()
    if not text:
        raise ValueError(HELP)
    if APP_ID_RE.match(text):
        return text
    url = parse_url(text)
    host = (url.hostname or "").lower()
    if host not in STORE_HOSTS:
        raise ValueError(HELP)
    parts = [p for p in url.path.split("/") if p]
    if len(parts) >= 2 and parts[0] == "app" and APP_ID_RE.match(parts[1]):
        return parts[1]
    raise ValueError(HELP)


def store_url(app_id):
    return "https://store.steampowered.com/app/" + app_id


def player_count(app_id):
    try:
        data = http_json(PLAYERS_API + "?" + urllib.parse.urlencode({"appid": app_id}))
    except HttpError as error:
        if error.code == 404:
            raise CounterError("no Steam app with id %s" % app_id)
        raise CounterError("Steam: HTTP %d" % error.code)
    response = data.get("response") if isinstance(data, dict) else None
    count = response.get("player_count") if isinstance(response, dict) else None
    if not isinstance(count, int):
        raise CounterError("no player count in the response")
    return count


def app_name(app_id):
    """The game's name from the store, or "" when the store will not say
    (a delisted app, a regional block, the store's rate limit). The reply
    is keyed by an id the store chooses, not always the one asked for, so
    the first entry is taken and its own app id checked."""
    try:
        data = http_json(DETAILS_API + "?" + urllib.parse.urlencode({"appids": app_id, "filters": "basic"}))
    except CounterError:
        return ""
    if not isinstance(data, dict) or not data:
        return ""
    entry = next(iter(data.values()))
    if not isinstance(entry, dict) or not entry.get("success"):
        return ""
    info = entry.get("data") or {}
    if str(info.get("steam_appid", app_id)) != str(app_id):
        return ""
    return str(info.get("name") or "")
