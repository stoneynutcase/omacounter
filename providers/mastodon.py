"""Shared Mastodon pieces: profile address parsing and the public lookup.
Registers no counter type itself; the mastodon_*.py files do.

Any instance serves GET /api/v1/accounts/lookup?acct=<user> without a key,
which is enough for followers and post counts."""

import re
import urllib.parse

from providers.base import CounterError, HttpError, http_json, parse_url

USER_RE = re.compile(r"^[A-Za-z0-9_]{1,30}$")
HOST_RE = re.compile(r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
NOT_MASTODON_HOSTS = ("youtube.com", "www.youtube.com", "youtu.be", "github.com", "www.github.com", "x.com", "twitter.com")

BRAND_COLOR = "#6364FF"
RATE_NOTE = "300 requests per 5 minutes per IP on a default instance"


def normalize_account(raw):
    """user@instance, @user@instance, https://instance/@user or
    https://instance/users/user → "user@instance"."""
    text = str(raw or "").strip()
    if not text:
        raise ValueError("an account is needed")
    user = host = ""
    if "://" in text or (("/" in text) and "@" in text.split("/", 1)[1]) or "/users/" in text:
        url = parse_url(text)
        host = url.netloc.lower()
        parts = [p for p in url.path.strip("/").split("/") if p]
        if host in NOT_MASTODON_HOSTS:
            raise ValueError("that is not a Mastodon profile")
        if parts and parts[0].startswith("@"):
            user = parts[0][1:]
        elif len(parts) >= 2 and parts[0] == "users":
            user = parts[1]
    else:
        handle = text[1:] if text.startswith("@") else text
        if "@" in handle:
            user, host = handle.split("@", 1)
            host = host.lower()
    if not user or not host:
        raise ValueError("a Mastodon account is user@instance or the profile URL (https://instance/@user)")
    if not USER_RE.match(user) or not HOST_RE.match(host):
        raise ValueError("a Mastodon account is user@instance or the profile URL (https://instance/@user)")
    return user + "@" + host


def split(target):
    user, host = target.split("@", 1)
    return user, host


def lookup(target):
    """The account object from the instance's public lookup endpoint."""
    user, host = split(target)
    url = "https://%s/api/v1/accounts/lookup?%s" % (host, urllib.parse.urlencode({"acct": user}))
    try:
        data = http_json(url)
    except HttpError as error:
        if error.code == 404:
            raise CounterError("no account %s on %s" % (user, host))
        if error.code in (401, 403):
            raise CounterError("%s does not allow public lookups" % host)
        if error.code == 429:
            raise CounterError("%s is rate limiting us" % host)
        raise CounterError("%s answered HTTP %d%s" % (host, error.code, (": " + error.message) if error.message else ""))
    if not isinstance(data, dict) or "username" not in data:
        raise CounterError("unexpected answer from " + host)
    return data


def profile_url(target):
    user, host = split(target)
    return "https://%s/@%s" % (host, user)


def display_name(data, target):
    return str(data.get("display_name") or data.get("username") or target)


# ---- tags -------------------------------------------------------------------
# GET /api/v1/tags/<name> is public too, but it carries a rolling seven-day
# history (uses and accounts per day), not an all-time total; the tag types
# count over that window, so their number can go down as days roll off.

TAG_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")


def normalize_tag(raw):
    """#tag@instance or https://instance/tags/tag → "#tag@instance"."""
    text = str(raw or "").strip()
    if not text:
        raise ValueError("a tag is needed")
    tag = host = ""
    if "://" in text or "/tags/" in text:
        url = parse_url(text)
        host = url.netloc.lower()
        parts = [p for p in url.path.strip("/").split("/") if p]
        if host in NOT_MASTODON_HOSTS:
            raise ValueError("that is not a Mastodon tag")
        if len(parts) >= 2 and parts[0] == "tags":
            tag = parts[1]
    elif text.startswith("#") and "@" in text:
        tag, host = text[1:].split("@", 1)
        host = host.lower()
    if not tag or not host:
        raise ValueError("a Mastodon tag is #tag@instance or the tag URL (https://instance/tags/tag)")
    if not TAG_RE.match(tag) or not HOST_RE.match(host):
        raise ValueError("a Mastodon tag is #tag@instance or the tag URL (https://instance/tags/tag)")
    return "#" + tag + "@" + host


def split_tag(target):
    tag, host = target[1:].split("@", 1)
    return tag, host


def tag_lookup(target):
    """The tag object, with its seven-day history, from the instance."""
    tag, host = split_tag(target)
    url = "https://%s/api/v1/tags/%s" % (host, urllib.parse.quote(tag))
    try:
        data = http_json(url)
    except HttpError as error:
        if error.code == 404:
            raise CounterError("no tag #%s on %s" % (tag, host))
        if error.code in (401, 403):
            raise CounterError("%s does not allow public tag lookups" % host)
        if error.code == 429:
            raise CounterError("%s is rate limiting us" % host)
        raise CounterError("%s answered HTTP %d%s" % (host, error.code, (": " + error.message) if error.message else ""))
    if not isinstance(data, dict) or not isinstance(data.get("history"), list):
        raise CounterError("unexpected answer from " + host)
    return data


def history_sum(data, field):
    total = 0
    for day in data.get("history") or []:
        try:
            total += int(day.get(field, 0) or 0)
        except (TypeError, ValueError, AttributeError):
            continue
    return total


def tag_url(target):
    tag, host = split_tag(target)
    return "https://%s/tags/%s" % (host, tag)


def tag_name(data, target):
    return "#" + str(data.get("name") or split_tag(target)[0])
