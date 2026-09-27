"""Shared Discord pieces: invite link parsing and the public invite lookup.
Registers no counter type itself; the discord_*.py files do.

GET https://discord.com/api/v10/invites/<code>?with_counts=true answers
without a token (it is what invite embeds use) with the server's name, its
approximate member count and how many members are online. The invite must
be a permanent one: an expiring invite dies, and the counter with it, so one
that carries an expiry is refused when the counter is added."""

import re
import urllib.parse

from providers.base import CounterError, HttpError, http_json, parse_url

API = "https://discord.com/api/v10/invites/"
CODE_RE = re.compile(r"^[A-Za-z0-9-]{2,64}$")
INVITE_HOSTS = ("discord.gg", "www.discord.gg", "discord.com", "www.discord.com", "discordapp.com", "www.discordapp.com")

BRAND_COLOR = "#5865F2"
RATE_NOTE = "an unauthenticated route without published limits; once every 5 minutes is well within what Discord serves invite embeds at"
HELP = "a Discord invite link: discord.gg/<code> (a permanent one; an invite that expires is refused)"


def normalize_invite(raw):
    """discord.gg/<code>, https://discord.com/invite/<code> or
    https://discordapp.com/invite/<code> → "discord.gg/<code>". A bare code
    is not accepted: on its own it could be anything, and a link is what
    Discord hands out."""
    text = str(raw or "").strip()
    if not text:
        raise ValueError(HELP)
    url = parse_url(text)
    host = (url.hostname or "").lower()
    if host not in INVITE_HOSTS:
        raise ValueError(HELP)
    parts = [p for p in url.path.split("/") if p]
    if host.endswith("discord.gg"):
        code = parts[0] if len(parts) == 1 else ""
    else:
        code = parts[1] if len(parts) == 2 and parts[0] == "invite" else ""
    if not CODE_RE.match(code):
        raise ValueError(HELP)
    return "discord.gg/" + code


def code_of(target):
    return str(target).split("/", 1)[1]


def invite_url(target):
    return "https://" + target


def lookup(target):
    """The invite document with counts. A missing, revoked or expired invite
    is a clean error; an invite that is going to expire is refused."""
    code = code_of(target)
    try:
        data = http_json(API + urllib.parse.quote(code) + "?" + urllib.parse.urlencode({"with_counts": "true", "with_expiration": "true"}))
    except HttpError as error:
        if error.code == 404:
            raise CounterError("invite not found (revoked, expired, or mistyped)")
        if error.code == 429:
            raise CounterError("Discord rate limit hit; it eases on its own")
        raise CounterError("HTTP %d%s" % (error.code, (": " + error.message) if error.message else ""))
    if not isinstance(data, dict) or not isinstance(data.get("guild"), dict):
        raise CounterError("that invite does not lead to a server")
    if data.get("expires_at"):
        raise CounterError("this invite expires (%s); make a permanent one for the counter" % str(data["expires_at"])[:10])
    return data


def server_name(data, target):
    name = (data.get("guild") or {}).get("name")
    return str(name) if name else target
