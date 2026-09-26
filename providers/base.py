"""The contracts every counter source fills, and the helpers they share.

A source is one file in this directory defining a subclass of `Provider`
(see DEVELOPING.md). Sources that need a key or token share a `Credential`
instance, defined once in a sibling module (providers/youtube.py holds the
YouTube API key), so several types can rely on one stored secret.

Nothing in here knows about the bar, shell.json or the wizard: the CLI reads
the registry and drives everything from these attributes and methods.
"""

import json
import os
import re
import socket
import stat
import urllib.error
import urllib.parse
import urllib.request

VERSION = "0.3.0"
USER_AGENT = "omacounter/" + VERSION + " (+https://github.com/stoneynutcase/omacounter)"
HTTP_TIMEOUT = 10
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_REDIRECTS = 3


# ------------------------------------------------------------ trusted helpers
# The programs this plugin starts on its own (the `gh` CLI for a token,
# `gum` for the wizard, `xdg-open`, Omarchy's own commands) are taken from
# the system directories by absolute path, and only when root owns the file
# and nobody else can write it. `PATH` is not consulted: ~/.local/bin is on
# most shells' PATH, and that is where anything able to write into the home
# directory would put a `gh` of its own. Omarchy's commands live in its
# install directory, held to the same rule.

TRUSTED_DIRS = ("/usr/local/bin", "/usr/bin", "/bin")
FIXED_PATH = ":".join(TRUSTED_DIRS)
OMARCHY_BIN = os.path.join(os.environ.get("OMARCHY_PATH") or "/usr/share/omarchy", "bin")
PYTHON = "/usr/bin/python3"


def _root_owned(st):
    return st.st_uid == 0 and not st.st_mode & (stat.S_IWGRP | stat.S_IWOTH)


def trusted_file(path, depth=0):
    """True when `path` is an executable regular file that root owns and
    nobody else can write, reached only through symlinks root owns that
    stay inside the trusted directories."""
    if depth > 8:
        return False
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        # Permission bits on a symlink mean nothing on Linux: ownership is
        # the whole check. /usr/bin/python3 is a link to whichever version
        # is installed today.
        if st.st_uid != 0:
            return False
        target = os.readlink(path)
        if not os.path.isabs(target):
            target = os.path.join(os.path.dirname(path), target)
        target = os.path.normpath(target)
        dirs = TRUSTED_DIRS + (OMARCHY_BIN,)
        if not any(target == d or target.startswith(d + "/") for d in dirs):
            return False
        return trusted_file(target, depth + 1)
    return bool(stat.S_ISREG(st.st_mode) and _root_owned(st) and st.st_mode & 0o111)


_TOOL_CACHE = {}


def trusted_tool(name, omarchy=False):
    """Absolute path of helper `name` in the trusted directories (Omarchy's
    own bin directory when `omarchy` is set), or None when there is no such
    file that passes `trusted_file`."""
    key = (name, omarchy)
    if key in _TOOL_CACHE:
        return _TOOL_CACHE[key]
    found = None
    for directory in ((OMARCHY_BIN,) if omarchy else TRUSTED_DIRS):
        try:
            st = os.stat(directory)
        except OSError:
            continue
        if not stat.S_ISDIR(st.st_mode) or not _root_owned(st):
            continue
        candidate = os.path.join(directory, name)
        if trusted_file(candidate):
            found = candidate
            break
    _TOOL_CACHE[key] = found
    return found


def minimal_env(keep=()):
    """An environment for a helper started on the plugin's behalf: a fixed
    PATH, the locale, the home and XDG directories, proxy settings, and
    whatever `keep` names beyond those. Nothing else survives, so a loader
    or trust override in the session cannot reach the helper."""
    names = ("HOME", "USER", "LANG", "LC_ALL", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME",
             "XDG_RUNTIME_DIR", "http_proxy", "https_proxy", "all_proxy", "no_proxy",
             "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY") + tuple(keep)
    env = {"PATH": FIXED_PATH}
    for name in names:
        value = os.environ.get(name)
        if value:
            env[name] = value
    return env


def scrub(text, secrets):
    """`text` with every value in `secrets` replaced, so a key never rides
    along in an error message, a report or a log."""
    out = str(text or "")
    for value in secrets:
        if value and len(str(value)) >= 8:
            out = out.replace(str(value), "•••")
    return out


# --------------------------------------------------------------------- errors


class CounterError(Exception):
    """Something a counter can report in its row: not found, no key, quota."""


class HttpError(CounterError):
    """A non-2xx answer. `message` and `reason` come from the JSON body when
    the service sends one (Google: error.message / error.errors[0].reason;
    GitHub and most others: a top-level message)."""

    def __init__(self, code, message="", reason=""):
        super().__init__(message or ("HTTP %d" % code))
        self.code = code
        self.message = message
        self.reason = reason


class Result:
    """What a provider hands back for one counter."""

    def __init__(self, value, name="", url=""):
        self.value = int(value)
        self.name = str(name or "")
        self.url = str(url or "")


# ----------------------------------------------------------------------- http


class HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to another https URL, and only a few times.
    Python's default would happily step down to plain http."""

    max_repeats = 2
    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise CounterError("redirect to a non-https address refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(HttpsOnlyRedirects())


def http_json(url, timeout=HTTP_TIMEOUT, headers=None):
    """GET a JSON document over https. The URL may carry an API key as a
    query parameter; the request is made in-process, so it never shows up in
    a command line, and the caller scrubs the key from any error text."""
    if urllib.parse.urlsplit(url).scheme != "https":
        raise CounterError("only https addresses are fetched")
    merged = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    merged.update(headers or {})
    request = urllib.request.Request(url, headers=merged)
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        body = b""
        try:
            body = error.read(MAX_RESPONSE_BYTES)
        except OSError:
            pass
        message, reason = "", ""
        try:
            parsed = json.loads(body)
            info = parsed.get("error") if isinstance(parsed, dict) else None
            if isinstance(info, dict):
                message = str(info.get("message", ""))
                errors = info.get("errors") or []
                if errors and isinstance(errors[0], dict):
                    reason = str(errors[0].get("reason", ""))
            elif isinstance(info, str):
                message = info
            elif isinstance(parsed, dict):
                message = str(parsed.get("message", ""))
        except (ValueError, AttributeError):
            pass
        raise HttpError(error.code, message, reason)
    except (urllib.error.URLError, socket.timeout, OSError) as error:
        reason = getattr(error, "reason", None) or error
        raise CounterError("network: %s" % reason)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise CounterError("response too large")
    try:
        return json.loads(raw)
    except ValueError:
        raise CounterError("malformed response")


def parse_url(raw):
    """urlparse that tolerates a missing scheme ("youtube.com/@x")."""
    text = str(raw or "").strip()
    if "://" not in text:
        text = "https://" + text
    return urllib.parse.urlparse(text)


# ---------------------------------------------------------------- formatting
# Mirrors Model.js (grouped / signed / entryTooltip) so the tooltip the CLI
# builds and the one the panel would build read the same.


def grouped(value):
    return "{:,}".format(int(value)) if isinstance(value, int) else "—"


def signed(delta):
    if not isinstance(delta, int):
        return ""
    if delta > 0:
        return "+" + grouped(delta)
    if delta < 0:
        return "−" + grouped(-delta)
    return "±0"


# A tooltip's name line is cut here (a video title can run to a hundred
# characters); Model.js holds the same number for its fallback.
TOOLTIP_LABEL_MAX = 40


def clip(text, limit=TOOLTIP_LABEL_MAX):
    """`text` cut to `limit` characters, an ellipsis counting as one."""
    text = str(text or "")
    if len(text) <= limit:
        return text
    return text[:max(0, limit - 1)].rstrip() + "…"


def default_tooltip(row):
    """Bar tooltip for one counter row: its name (cut to TOOLTIP_LABEL_MAX
    characters), the exact number, how it moved today when known, and the
    error when it is stale or failed."""
    label = clip(row.get("label") or row.get("type") or "")
    error = row.get("error")
    value = row.get("value")
    if error and value is None:
        return label + "\n" + str(error)
    line = grouped(value) + ((" " + row["unit"]) if row.get("unit") else "")
    if isinstance(row.get("deltaDay"), int):
        line += "  ·  " + signed(row["deltaDay"]) + " today"
    if error:
        line += "\nstale: " + str(error)
    return label + "\n" + line


# ------------------------------------------------------------------ contracts


class Credential:
    """One stored secret that one or more providers need.

    Define a subclass in the module the providers share, instantiate it once
    at module level, and point each provider's `credential` at that instance.
    The CLI's `auth <id>` command, the wizard and `doctor` are generic over
    these attributes; only `verify` and `hint_for` are usually overridden.

      id           the key in secrets.json and the name in `auth <id>`
      kind         "api_key" or "token": the field name inside secrets.json
      label        "YouTube API key": headings, doctor lines, errors
      help         the paragraph the wizard prints: what it is, where to get
                   it, what it can read, what it costs
      console_url  the page to open to obtain one, or ""
      env          environment variable consulted after the file, or ""
      placeholder  the input placeholder, e.g. "AIza…"
      shape        what a pasted value must look like (regex)
      shape_help   how to say `shape` in words
    """

    id = ""
    kind = "api_key"
    label = ""
    help = ""
    console_url = ""
    env = ""
    placeholder = ""
    shape = re.compile(r"^\S{8,256}$")
    shape_help = "no spaces, at least 8 characters"

    FIELDS = {"api_key": "apiKey", "token": "token"}

    @property
    def field(self):
        return self.FIELDS[self.kind]

    def verify(self, value):
        """One cheap request that fails the way a real fetch would. Raise
        CounterError with a one-line reason; return normally when it works."""

    def hint_for(self, error):
        """Extra advice printed after a failed verify, or ""."""
        return ""

    # ---- generic, not meant to be overridden

    def from_file(self, secrets):
        section = secrets.get(self.id) if isinstance(secrets, dict) else None
        if not isinstance(section, dict):
            return ""
        return str(section.get(self.field, "") or "").strip()

    def from_env(self):
        import os
        return os.environ.get(self.env, "").strip() if self.env else ""

    def present(self, secrets):
        return bool(self.from_file(secrets) or self.from_env())

    def source(self, secrets):
        """Where the value in use comes from, for `auth` and `doctor`:
        "file", "env <NAME>", or "" when there is none. Subclasses that look
        further afield (a CLI's login) say so here."""
        if self.from_file(secrets):
            return "file"
        if self.from_env():
            return "env " + self.env
        return ""

    def resolve(self, secrets):
        value = self.from_file(secrets) or self.from_env()
        if not value:
            raise CounterError("no %s — run: omacounter auth %s set" % (self.label, self.id))
        return value

    def store(self, secrets, value):
        secrets.setdefault(self.id, {})[self.field] = str(value).strip()

    def clear(self, secrets):
        secrets.pop(self.id, None)

    def masked(self, value):
        value = str(value or "")
        if len(value) <= 10:
            return "•" * len(value)
        return value[:6] + "…" + value[-4:]


class Provider:
    """One kind of counter.

    Subclasses set the attributes and implement `normalize` and `fetch`. The
    rest of the program is generic: `add`, `setup`, `list`, `types`, `doctor`
    and `fetch` read the registry. One file per subclass, named after the id
    with the dot as an underscore (youtube_likes.py defines youtube.likes).

      id               the `type` written on a counter: "<service>.<metric>"
      label            default label before the first fetch resolves a name
      unit             word after the number: "subscribers"
      icon             one Nerd Font glyph shown before the number
      brand_color      default glyph colour "#RRGGBB", or "" to follow the bar;
                       a counter's glyphColor or color wins
      text_color       default number colour, same values and precedence
      target_help      what `target` should contain: "video id or video URL"
      target_kind      "channel" | "video" | "repository" | …; the wizard says
                       "That is a video — count what?" from it
      accepts          phrase for the wizard prompt: "a YouTube video (URL or id)"
      describe         one line for `types`: "likes on one YouTube video"
      example          a valid canonical target, shown by `types` and checked
                       by the tests (normalize(example) == example)
      credential       the Credential instance this needs, or None
      default_interval minutes between fetches when the counter and the widget
                       set none; None = the widget's refreshMinutes
      min_interval     minutes: the fastest this source may be polled. The
                       fetch loop enforces it whatever the counter or widget
                       asks for, hard refresh included
      rate_note        why the cap is what it is, shown by `types`, `doctor`
                       and `set`: "60 requests an hour per IP without a token"
      order            sort key within the registry (then file name). Decides
                       the order `types` lists and, when one link fits several
                       types, which the wizard preselects: put the keyless,
                       most-wanted type first
      group            which service this belongs to, for the panel's section
                       headers: "youtube". Defaults to the part of `id` before
                       the dot, so siblings group together with no effort
      group_label      how that group is titled: "YouTube". Defaults to the
                       group capitalised
    """

    order = 100
    group = ""
    group_label = ""

    @property
    def group_key(self):
        return self.group or (self.id.split(".")[0] if self.id else "")

    @property
    def group_name(self):
        return self.group_label or self.group_key.capitalize()

    id = ""
    label = ""
    unit = ""
    icon = ""
    brand_color = ""
    text_color = ""
    target_help = ""
    target_kind = ""
    accepts = ""
    describe = ""
    example = ""
    credential = None
    default_interval = None
    min_interval = 1
    rate_note = ""

    def normalize(self, target):
        """Canonical form of `target` (used as the cache key). Raise ValueError
        with a sentence a person can act on; the wizard prints it and asks
        again. When the input clearly belongs to a sibling type, say so."""
        text = str(target or "").strip()
        if not text:
            raise ValueError("a target is needed")
        return text

    def fetch(self, target, secrets):
        """Return a Result, or raise CounterError with a one-line reason.
        Runs in a worker thread alongside other providers' fetches."""
        raise NotImplementedError

    def url(self, target):
        """Page to open for this counter, or ""."""
        return ""

    def secret(self, secrets):
        """The credential's value, or None when the provider needs none."""
        return self.credential.resolve(secrets) if self.credential else None

    def tooltip(self, row):
        """Bar tooltip for a fetched row. Override to add or reword."""
        return default_tooltip(row)
