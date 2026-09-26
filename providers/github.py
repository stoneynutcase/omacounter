"""Shared GitHub pieces: the token credential, request helpers, the
repository address parser. Registers no counter type itself; the
github_*.py files do.

Public repository data needs no token (60 requests an hour per IP; the
search endpoint 10 a minute). Traffic data — cloners, visitors — is shown
only to people with push access, so it needs a token. When a token is
available it is sent on every GitHub request, which also lifts the rate
limit to 5,000 an hour. The `gh` CLI's login counts as a token, so a
machine where `gh auth login` has been run needs nothing stored."""

import re
import shutil
import subprocess
import urllib.parse

from providers.base import CounterError, Credential, HttpError, http_json, parse_url

API = "https://api.github.com"
HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
REPO_RE = re.compile(r"^([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9._-]{1,100})$")
SSH_RE = re.compile(r"^git@github\.com:(?P<path>.+)$")

RATE_NOTE = "60 requests an hour per IP without a token, 5,000 with one"
SEARCH_RATE_NOTE = "the search API allows 10 requests a minute without a token, 30 with one"
TRAFFIC_RATE_NOTE = "traffic numbers update about once a day"

STAR_COLOR = "#E3B341"    # GitHub's star yellow
OPEN_COLOR = "#3FB950"    # GitHub's "open" green
PULL_COLOR = "#8957E5"    # GitHub's pull-request purple
CLONE_COLOR = "#58A6FF"   # GitHub's link blue


def gh_cli_token():
    """The token the `gh` CLI is logged in with, or "". One subprocess per
    fetch run is acceptable; the result is cached for the process."""
    if gh_cli_token.cached is not None:
        return gh_cli_token.cached
    token = ""
    if shutil.which("gh"):
        try:
            result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                token = result.stdout.strip()
        except (subprocess.SubprocessError, OSError):
            token = ""
    gh_cli_token.cached = token
    return token


gh_cli_token.cached = None


class GitHubToken(Credential):
    id = "github"
    kind = "token"
    label = "GitHub token"
    help = ("Cloners and visitors are shown only to people with push access, so GitHub needs a "
            "token that can read the repository. Settings → Developer settings → Personal "
            "access tokens: a fine-grained token with read access to the repository (Administration "
            "and Metadata), or a classic token with the repo scope. If the gh CLI is logged in on "
            "this machine, its login is used automatically and nothing needs to be stored.")
    console_url = "https://github.com/settings/tokens"
    env = "GITHUB_TOKEN"
    placeholder = "ghp_… or github_pat_…"
    shape = re.compile(r"^(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})$")
    shape_help = "ghp_…, gho_… or github_pat_… followed by letters and digits"

    def from_env(self):
        import os
        for name in ("GITHUB_TOKEN", "GH_TOKEN"):
            value = os.environ.get(name, "").strip()
            if value:
                return value
        return gh_cli_token()

    def source(self, secrets):
        import os
        if self.from_file(secrets):
            return "file"
        for name in ("GITHUB_TOKEN", "GH_TOKEN"):
            if os.environ.get(name, "").strip():
                return "env " + name
        return "gh login" if gh_cli_token() else ""

    def verify(self, value):
        try:
            http_json(API + "/user", headers=auth_headers(value))
        except HttpError as error:
            if error.code == 401:
                raise CounterError("GitHub rejected the token")
            raise CounterError(error_text(error))


CREDENTIAL = GitHubToken()


def auth_headers(token):
    headers = dict(HEADERS)
    if token:
        headers["Authorization"] = "Bearer " + token
    return headers


def optional_token(secrets):
    """A token when one is available, else "": public data works without."""
    try:
        return CREDENTIAL.resolve(secrets)
    except CounterError:
        return ""


def error_text(error):
    if error.code == 404:
        return "not found"
    if error.code in (403, 429):
        if "rate limit" in (error.message or "").lower():
            return "GitHub API rate limit exceeded (%s)" % RATE_NOTE
        return "GitHub refused (HTTP %d): %s" % (error.code, error.message or "no access")
    if error.code == 401:
        return "GitHub rejected the token — run: omacounter auth github set"
    if error.code == 451:
        return "unavailable for legal reasons"
    return "HTTP %d%s" % (error.code, (": " + error.message) if error.message else "")


def get(path, token="", params=None):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        return http_json(url, headers=auth_headers(token))
    except HttpError as error:
        raise CounterError(error_text(error))


def repo_json(repo, secrets):
    data = get("/repos/" + repo, optional_token(secrets))
    if not isinstance(data, dict):
        raise CounterError("unexpected answer from GitHub")
    return data


def search_count(repo, qualifiers, secrets):
    """total_count of an issues search scoped to one repository."""
    query = "repo:%s %s" % (repo, qualifiers)
    data = get("/search/issues", optional_token(secrets), {"q": query, "per_page": 1, "advanced_search": "true"})
    if not isinstance(data, dict) or "total_count" not in data:
        raise CounterError("unexpected answer from GitHub search")
    return int(data["total_count"])


# ---- targets ---------------------------------------------------------------


def is_github_url(text):
    return "github.com" in text


def repo_from_text(text):
    """"owner/repo" from a bare pair, a github.com URL (any deeper path),
    a .git clone URL or an SSH clone address; "" when it is none of those."""
    ssh = SSH_RE.match(text)
    path = ""
    if ssh:
        path = ssh.group("path")
    elif is_github_url(text):
        url = parse_url(text)
        if url.netloc not in ("github.com", "www.github.com"):
            return ""
        path = url.path
    elif "/" in text and "://" not in text and "." not in text.split("/")[0]:
        path = text
    else:
        return ""
    parts = [p for p in path.strip("/").split("/") if p]
    if len(parts) < 2:
        return ""
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    candidate = owner + "/" + repo
    return candidate if REPO_RE.match(candidate) else ""


def normalize_repo(raw):
    text = str(raw or "").strip()
    if not text:
        raise ValueError("a repository is needed")
    repo = repo_from_text(text)
    if repo:
        return repo
    raise ValueError("a repository is owner/repo or its github.com URL")


def repo_url(repo):
    return "https://github.com/" + repo
