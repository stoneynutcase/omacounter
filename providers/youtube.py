"""Shared YouTube pieces: the API key credential, the Data API client, and
the channel / video target parsers. Registers no counter type itself; the
youtube_*.py files do."""

import re
import urllib.parse

from providers.base import CounterError, Credential, HttpError, http_json, parse_url

API = "https://www.googleapis.com/youtube/v3/"
CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
HANDLE_RE = re.compile(r"^@?([A-Za-z0-9._-]{3,30})$")
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

BRAND_COLOR = "#FF0000"
RATE_NOTE = "1 quota unit per fetch, 10,000 a day"


class YouTubeKey(Credential):
    id = "youtube"
    kind = "api_key"
    label = "YouTube API key"
    help = ("YouTube's numbers come from the official Data API, which needs a free key. "
            "It takes about two minutes: create a Google Cloud project, enable "
            "\"YouTube Data API v3\", then Credentials → Create credentials → API key. "
            "The key only reads public statistics; 10,000 calls a day is the quota, "
            "and every refresh costs one.")
    console_url = "https://console.cloud.google.com/apis/library/youtube.googleapis.com"
    env = "YOUTUBE_API_KEY"
    placeholder = "AIza…"
    shape = re.compile(r"^[A-Za-z0-9_-]{20,128}$")
    shape_help = "letters, digits, - and _"

    def verify(self, value):
        """One cheap call (1 quota unit) that fails the way a real fetch would."""
        call("videos", {"part": "id", "id": "dQw4w9WgXcQ"}, value)

    def hint_for(self, error):
        if "not enabled" in str(error):
            return "Enable \"YouTube Data API v3\" for the project the key belongs to, then paste it again."
        return ""


CREDENTIAL = YouTubeKey()


def error_text(error):
    """Turn a Google API error into the one line the panel shows."""
    if error.code == 400:
        return "API key rejected (HTTP 400)"
    if error.code == 403:
        if error.reason == "quotaExceeded":
            return "YouTube API daily quota exceeded"
        if error.reason in ("accessNotConfigured", "forbidden") and "not been used" in error.message:
            return "YouTube Data API v3 is not enabled for this key"
        return "forbidden (HTTP 403): %s" % (error.message or error.reason or "check the API key")
    if error.code == 404:
        return "not found"
    return "HTTP %d%s" % (error.code, (": " + error.message) if error.message else "")


def call(resource, params, key):
    query = dict(params)
    query["key"] = key
    url = API + resource + "?" + urllib.parse.urlencode(query)
    try:
        return http_json(url)
    except HttpError as error:
        raise CounterError(error_text(error))


def first_item(data, what):
    items = data.get("items") or []
    if not items:
        raise CounterError(what + " not found")
    return items[0]


# ---- targets ---------------------------------------------------------------


def is_youtube_url(text):
    return "youtube.com" in text or "youtu.be" in text


def channel_from_url(text):
    """"@handle" or "UC…" from a channel URL, or "" when the URL is not one."""
    path = urllib.parse.unquote(parse_url(text).path).strip("/")
    parts = path.split("/") if path else []
    if parts and parts[0].startswith("@") and HANDLE_RE.match(parts[0]):
        return "@" + HANDLE_RE.match(parts[0]).group(1)
    if len(parts) >= 2 and parts[0] == "channel" and CHANNEL_ID_RE.match(parts[1]):
        return parts[1]
    return ""


def video_from_url(text):
    """The 11-character id from a video URL, or "" when the URL is not one."""
    url = parse_url(text)
    candidate = ""
    if url.netloc.endswith("youtu.be"):
        candidate = url.path.strip("/").split("/")[0] if url.path.strip("/") else ""
    else:
        candidate = (urllib.parse.parse_qs(url.query).get("v") or [""])[0]
        if not candidate:
            parts = url.path.strip("/").split("/")
            if len(parts) >= 2 and parts[0] in ("shorts", "live", "embed", "v"):
                candidate = parts[1]
    return candidate if VIDEO_ID_RE.match(candidate) else ""


def normalize_channel(raw):
    """@handle, UC… id, or a channel URL → "@handle" or "UC…"."""
    text = str(raw or "").strip()
    if not text:
        raise ValueError("a channel is needed")
    if is_youtube_url(text):
        channel = channel_from_url(text)
        if channel:
            return channel
        if video_from_url(text):
            raise ValueError("that is a video link — a subscribers counter needs the channel "
                             "(youtube.com/@name); for the video's likes use the type youtube.likes")
        raise ValueError("use the channel's @handle or its UC… id (youtube.com/@name or youtube.com/channel/UC…)")
    if CHANNEL_ID_RE.match(text):
        return text
    match = HANDLE_RE.match(text)
    if match:
        return "@" + match.group(1)
    raise ValueError("a channel is an @handle, a UC… id, or a channel URL")


def normalize_video(raw):
    """Video id or any youtube.com / youtu.be video URL → the 11-character id."""
    text = str(raw or "").strip()
    if not text:
        raise ValueError("a video is needed")
    if is_youtube_url(text):
        video = video_from_url(text)
        if video:
            return video
        if channel_from_url(text):
            raise ValueError("that is a channel link — a likes counter needs a video "
                             "(youtube.com/watch?v=… or youtu.be/…); for the channel's subscribers use the type youtube.subscribers")
        raise ValueError("that URL has no video id in it")
    if VIDEO_ID_RE.match(text):
        return text
    raise ValueError("a video id is 11 characters — or paste the video's URL")


def video_url(video_id):
    return "https://www.youtube.com/watch?v=" + video_id


def channel_url(target):
    if target.startswith("@"):
        return "https://www.youtube.com/" + target
    return "https://www.youtube.com/channel/" + target
