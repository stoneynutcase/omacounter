"""Offline tests for bin/omacounter and the providers package.

The script has no .py extension, so it is loaded as a module by path; that
also puts the plugin root on sys.path, so `providers` here is the very same
package the CLI registered. Every test points the config, state and secrets
paths at a temporary directory and replaces providers' fetch() with fakes, so
nothing here needs a network or a key. The live tests at the bottom run only
with YOUTUBE_API_KEY (YouTube) or OMACOUNTER_LIVE=1 (GitHub) set.
"""

import datetime as dt
import importlib.machinery
import importlib.util
import inspect
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.request
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "bin", "omacounter")


def load_cli():
    loader = importlib.machinery.SourceFileLoader("omacounter", SCRIPT)
    spec = importlib.util.spec_from_loader("omacounter", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


cli = load_cli()
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import providers  # noqa: E402
from providers import base, discord, github, mastodon, youtube  # noqa: E402

SHARED_MODULES = {"base.py", "youtube.py", "mastodon.py", "github.py", "discord.py"}


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="omacounter-test-")
        self.addCleanup(shutil.rmtree, self.tmp)
        self._saved = {k: getattr(cli, k) for k in ("SECRETS_PATH", "STATE_PATH", "SHELL_JSON")}
        cli.SECRETS_PATH = os.path.join(self.tmp, "secrets.json")
        cli.STATE_PATH = os.path.join(self.tmp, "state.json")
        cli.SHELL_JSON = os.path.join(self.tmp, "shell.json")
        self._fetches = {}
        for pid, provider in cli.PROVIDERS.items():
            self._fetches[pid] = provider.__class__.fetch
        self._verify = youtube.YouTubeKey.verify
        self.addCleanup(self.restore)

    def restore(self):
        for k, v in self._saved.items():
            setattr(cli, k, v)
        for pid, original in self._fetches.items():
            cli.PROVIDERS[pid].__class__.fetch = original
        youtube.YouTubeKey.verify = self._verify

    def fake(self, provider_id, fn):
        cli.PROVIDERS[provider_id].__class__.fetch = lambda self, target, secrets: fn(target, secrets)

    def write_shell(self, counters=None, present=True):
        entry = {"id": cli.PLUGIN_ID}
        if counters is not None:
            entry["counters"] = counters
        layout = {"left": [{"id": "omarchy.menu"}], "center": [], "right": [entry] if present else []}
        with open(cli.SHELL_JSON, "w") as fh:
            json.dump({"version": 1, "bar": {"layout": layout}, "plugins": []}, fh)

    def run_cli(self, argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main(argv)
        return code, out.getvalue()


# ------------------------------------------------------------------ discovery


class Discovery(unittest.TestCase):
    def test_registry(self):
        self.assertEqual(set(cli.PROVIDERS), {"github.stars", "github.issues", "github.pulls", "github.clones",
                                              "mastodon.followers", "mastodon.posts", "mastodon.tag", "mastodon.tagpeople",
                                              "youtube.subscribers", "youtube.likes", "youtube.views",
                                              "discord.members", "discord.online"})
        self.assertEqual(providers.LOAD_ERRORS, [])
        self.assertEqual(list(cli.PROVIDERS)[:4], ["github.stars", "github.issues", "github.pulls", "github.clones"])  # `order`, then file name

    def test_file_naming_convention(self):
        registered = set()
        for pid, provider in cli.PROVIDERS.items():
            filename = os.path.basename(inspect.getfile(type(provider)))
            self.assertEqual(filename, pid.replace(".", "_") + ".py", pid)
            registered.add(filename)
        on_disk = {n for n in os.listdir(providers.PROVIDERS_DIR) if n.endswith(".py") and not n.startswith("_")}
        self.assertEqual(on_disk - SHARED_MODULES, registered, "every provider file registers exactly one type")

    def test_broken_file_is_reported_not_fatal(self):
        tmp = tempfile.mkdtemp(prefix="omacounter-providers-")
        self.addCleanup(shutil.rmtree, tmp)
        with open(os.path.join(tmp, "good_one.py"), "w") as fh:
            fh.write("from providers.base import Provider\n"
                     "class GoodOne(Provider):\n"
                     "    id = 'good.one'; label = 'Good'; unit = 'u'; icon = 'x'\n"
                     "    def fetch(self, t, s): raise NotImplementedError\n")
        with open(os.path.join(tmp, "zz_broken.py"), "w") as fh:
            fh.write("this is not python (\n")
        before = len(providers.LOAD_ERRORS)
        registry = providers.load_from(tmp, package="omacounter_test_providers")
        self.assertEqual(list(registry), ["good.one"])
        self.assertEqual(len(providers.LOAD_ERRORS), before + 1)
        name, error = providers.LOAD_ERRORS[-1]
        self.assertEqual(name, "zz_broken.py")
        self.assertIn("SyntaxError", error)
        del providers.LOAD_ERRORS[-1]
        sys.modules.pop("omacounter_test_providers.good_one", None)


class Contract(unittest.TestCase):
    SAMPLE_ROW = {"label": "X", "value": 12, "unit": "u", "error": None, "deltaDay": 1, "type": "t"}

    def test_every_provider_is_complete(self):
        for pid, provider in cli.PROVIDERS.items():
            self.assertEqual(pid, provider.id)
            self.assertRegex(pid, r"^[a-z0-9]+\.[a-z0-9]+$")
            for attr in ("label", "unit", "icon", "target_help", "target_kind", "accepts", "describe", "example"):
                self.assertTrue(getattr(provider, attr), "%s.%s is empty" % (pid, attr))
            self.assertEqual(len(provider.icon), 1, pid)
            for attr in ("brand_color", "text_color"):
                if getattr(provider, attr):
                    self.assertRegex(getattr(provider, attr), r"^#[0-9A-Fa-f]{6}$", pid)
            self.assertEqual(provider.normalize(provider.example), provider.example, pid)
            self.assertTrue(provider.url(provider.example).startswith("https://"), pid)
            self.assertIsInstance(provider.tooltip(dict(self.SAMPLE_ROW)), str, pid)
            self.assertGreaterEqual(provider.min_interval, 1, pid)
            self.assertEqual(provider.group_key, pid.split(".")[0], pid)
            self.assertTrue(provider.group_name and provider.group_name != provider.group_key, "%s needs a proper group_label" % pid)
            if provider.min_interval > 1:
                self.assertTrue(provider.rate_note, "%s caps polling but says nothing about why" % pid)
            if provider.credential is not None:
                cred = provider.credential
                self.assertIsInstance(cred, base.Credential)
                for attr in ("id", "label", "env"):
                    self.assertTrue(getattr(cred, attr), "%s credential %s is empty" % (pid, attr))
                self.assertIn(cred.kind, base.Credential.FIELDS)
                self.assertTrue(hasattr(cred.shape, "match"))

    def test_credentials_registry(self):
        self.assertEqual(set(cli.CREDENTIALS), {"youtube", "github"})
        self.assertIs(cli.PROVIDERS["youtube.likes"].credential, cli.PROVIDERS["youtube.subscribers"].credential)
        self.assertIsNone(cli.PROVIDERS["github.stars"].credential)
        self.assertIs(cli.PROVIDERS["github.clones"].credential, github.CREDENTIAL)
        self.assertEqual(github.CREDENTIAL.kind, "token")


# -------------------------------------------------------------------- youtube


class NormalizeChannel(unittest.TestCase):
    def test_forms(self):
        n = youtube.normalize_channel
        self.assertEqual(n("@omarchy"), "@omarchy")
        self.assertEqual(n("omarchy"), "@omarchy")
        self.assertEqual(n("  @Omarchy.dev "), "@Omarchy.dev")
        self.assertEqual(n("https://www.youtube.com/@omarchy"), "@omarchy")
        self.assertEqual(n("youtube.com/@omarchy/videos"), "@omarchy")
        self.assertEqual(n("UCBR8-60-B28hp2BmDPdntcQ"), "UCBR8-60-B28hp2BmDPdntcQ")
        self.assertEqual(n("https://www.youtube.com/channel/UCBR8-60-B28hp2BmDPdntcQ"), "UCBR8-60-B28hp2BmDPdntcQ")

    def test_rejects(self):
        for bad in ("", "https://www.youtube.com/c/legacyname", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "a b"):
            with self.assertRaises(ValueError):
                youtube.normalize_channel(bad)

    def test_video_link_is_named_as_such(self):
        with self.assertRaises(ValueError) as caught:
            youtube.normalize_channel("https://www.youtube.com/watch?v=PycJU-g5sHQ")
        self.assertIn("video link", str(caught.exception))
        self.assertIn("youtube.likes", str(caught.exception))

    def test_detect_providers(self):
        video = [p.id for p in cli.detect_providers("https://www.youtube.com/watch?v=PycJU-g5sHQ")]
        self.assertEqual(video, ["youtube.likes", "youtube.views"])
        channel = [p.id for p in cli.detect_providers("youtube.com/@omarchy")]
        self.assertEqual(channel, ["youtube.subscribers"])
        self.assertEqual([p.id for p in cli.detect_providers("github.com/o/r")][0], "github.stars")
        self.assertEqual(cli.detect_providers("https://example.com/nothing"), [])
        self.assertIsNone(cli.detect_provider("https://example.com/nothing"))

    def test_views_provider(self):
        views = cli.PROVIDERS["youtube.views"]
        self.assertEqual(views.normalize("https://youtu.be/PycJU-g5sHQ"), "PycJU-g5sHQ")
        self.assertEqual(views.icon, "\U000F06D0")
        self.assertEqual(views.brand_color, "#FF0000")
        self.assertEqual(views.url("PycJU-g5sHQ"), "https://www.youtube.com/watch?v=PycJU-g5sHQ")


class NormalizeVideo(unittest.TestCase):
    def test_forms(self):
        n = youtube.normalize_video
        self.assertEqual(n("dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(n("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s"), "dQw4w9WgXcQ")
        self.assertEqual(n("https://youtu.be/dQw4w9WgXcQ?si=abc"), "dQw4w9WgXcQ")
        self.assertEqual(n("youtu.be/dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(n("https://www.youtube.com/shorts/dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(n("https://www.youtube.com/live/dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(n("https://www.youtube.com/embed/dQw4w9WgXcQ"), "dQw4w9WgXcQ")

    def test_rejects(self):
        for bad in ("", "tooshort", "https://www.youtube.com/@omarchy", "https://youtu.be/"):
            with self.assertRaises(ValueError):
                youtube.normalize_video(bad)

    def test_hyphenated_id_and_channel_link_message(self):
        self.assertEqual(youtube.normalize_video("https://www.youtube.com/watch?v=PycJU-g5sHQ"), "PycJU-g5sHQ")
        with self.assertRaises(ValueError) as caught:
            youtube.normalize_video("https://www.youtube.com/@omarchy")
        self.assertIn("channel link", str(caught.exception))
        self.assertIn("youtube.subscribers", str(caught.exception))


class ErrorText(unittest.TestCase):
    def test_google_errors(self):
        self.assertIn("rejected", youtube.error_text(base.HttpError(400, "API key not valid", "badRequest")))
        self.assertIn("quota", youtube.error_text(base.HttpError(403, "Quota exceeded", "quotaExceeded")))
        self.assertIn("not enabled", youtube.error_text(base.HttpError(403, "YouTube Data API v3 has not been used in project 1 before", "accessNotConfigured")))
        self.assertEqual(youtube.error_text(base.HttpError(404, "", "")), "not found")
        self.assertIs(cli.HttpError, base.HttpError)


# --------------------------------------------------------------------- github


class GitHub(Sandbox):
    def setUp(self):
        super().setUp()
        self._http = github.http_json
        self._gh_cached = github.gh_cli_token.cached
        github.gh_cli_token.cached = ""          # no gh CLI login during the tests
        for name in ("GITHUB_TOKEN", "GH_TOKEN"):
            os.environ.pop(name, None)
        self.addCleanup(self.restore_github)

    def restore_github(self):
        github.http_json = self._http
        github.gh_cli_token.cached = self._gh_cached

    def fake_http(self, fn):
        github.http_json = lambda url, timeout=10, headers=None: fn(url, headers or {})

    def test_normalize(self):
        n = cli.PROVIDERS["github.stars"].normalize
        for raw in ("octocat/Hello-World", "https://github.com/octocat/Hello-World", "github.com/octocat/Hello-World/issues/1",
                    "https://github.com/octocat/Hello-World.git", "git@github.com:octocat/Hello-World.git", "www.github.com/octocat/Hello-World"):
            self.assertEqual(n(raw), "octocat/Hello-World", raw)
        for bad in ("", "octocat", "https://gitlab.com/o/r", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube.com/@omarchy", "-bad/repo"):
            with self.assertRaises(ValueError, msg=bad):
                n(bad)
        self.assertEqual(n("a/b/c"), "a/b")  # deeper paths keep the repository
        self.assertEqual([p.id for p in cli.detect_providers("octocat/Hello-World")],
                         ["github.stars", "github.issues", "github.pulls", "github.clones"])

    def test_stars_through_report(self):
        def repo(url, headers):
            self.assertEqual(url, "https://api.github.com/repos/octocat/Hello-World")
            self.assertIn("Accept", headers)
            self.assertNotIn("Authorization", headers)
            return {"stargazers_count": 42, "full_name": "octocat/Hello-World", "html_url": "https://github.com/octocat/Hello-World"}

        self.fake_http(repo)
        row = cli.fetch_all([{"type": "github.stars", "target": "https://github.com/octocat/Hello-World"}], now=0)["counters"][0]
        self.assertEqual(row["value"], 42)
        self.assertEqual(row["label"], "octocat/Hello-World")
        self.assertEqual(row["brandColor"], "#E3B341")
        self.assertEqual(row["unit"], "stars")
        self.assertEqual(row["icon"], "\U000F04CE")
        self.assertEqual(row["credential"], "")
        self.assertEqual(row["effectiveInterval"], 15)
        self.assertEqual(row["tooltip"], "octocat/Hello-World\n42 stars")

    def test_issues_and_pulls_use_search(self):
        seen = []

        def search(url, headers):
            seen.append(url)
            return {"total_count": 1079 if "is%3Aissue" in url else 16}

        self.fake_http(search)
        rows = cli.fetch_all([{"type": "github.issues", "target": "omacom/omarchy-plugin-marketplace"},
                              {"type": "github.pulls", "target": "omacom/omarchy-plugin-marketplace"}], now=0)["counters"]
        self.assertEqual([r["value"] for r in rows], [1079, 16])
        self.assertEqual([r["unit"] for r in rows], ["open issues", "open pull requests"])
        self.assertEqual(rows[0]["url"], "https://github.com/omacom/omarchy-plugin-marketplace/issues")
        for url in seen:
            self.assertTrue(url.startswith("https://api.github.com/search/issues?"), url)
            self.assertIn("repo%3Aomacom%2Fomarchy-plugin-marketplace", url)
            self.assertIn("advanced_search=true", url)
        self.assertIn("is%3Aissue+is%3Aopen", seen[0])
        self.assertIn("is%3Apr+is%3Aopen", seen[1])

    def test_clones_need_a_token(self):
        row = cli.fetch_all([{"type": "github.clones", "target": "stoneynutcase/omagif"}], now=0)["counters"][0]
        self.assertIsNone(row["value"])
        self.assertIn("no GitHub token", row["error"])
        self.assertIn("auth github set", row["error"])
        self.assertEqual(row["credential"], "github")
        self.assertEqual(row["effectiveInterval"], 60)  # the provider's default, above the widget's 15

    def test_clones_with_a_token(self):
        os.environ["GITHUB_TOKEN"] = "ghp_" + "a" * 36
        self.addCleanup(os.environ.pop, "GITHUB_TOKEN", None)

        def traffic(url, headers):
            self.assertEqual(url, "https://api.github.com/repos/stoneynutcase/omagif/traffic/clones")
            self.assertEqual(headers.get("Authorization"), "Bearer ghp_" + "a" * 36)
            return {"count": 151, "uniques": 51, "clones": []}

        self.fake_http(traffic)
        row = cli.fetch_all([{"type": "github.clones", "target": "stoneynutcase/omagif"}], now=0)["counters"][0]
        self.assertEqual(row["value"], 51)
        self.assertEqual(row["unit"], "unique cloners (14 days)")
        self.assertEqual(row["url"], "https://github.com/stoneynutcase/omagif/graphs/traffic")

    def test_gh_cli_login_counts_as_a_token(self):
        github.gh_cli_token.cached = "gho_" + "b" * 36
        self.assertTrue(github.CREDENTIAL.present({}))
        self.assertEqual(github.CREDENTIAL.resolve({}), "gho_" + "b" * 36)
        self.assertEqual(github.optional_token({"github": {"token": "ghp_" + "c" * 36}}), "ghp_" + "c" * 36)  # the file wins

    def test_token_shape_and_errors(self):
        for good in ("ghp_" + "a" * 36, "gho_" + "a" * 36, "github_pat_" + "A1_" * 10):
            self.assertTrue(github.CREDENTIAL.shape.match(good), good)
        for bad in ("", "AIzaSy" + "x" * 30, "ghp_short"):
            self.assertFalse(github.CREDENTIAL.shape.match(bad), bad)
        self.fake_http(lambda url, headers: (_ for _ in ()).throw(base.HttpError(404, "Not Found")))
        with self.assertRaises(base.CounterError) as caught:
            cli.PROVIDERS["github.stars"].fetch("octocat/Hello-World", {})
        self.assertEqual(str(caught.exception), "not found")
        self.fake_http(lambda url, headers: (_ for _ in ()).throw(base.HttpError(403, "API rate limit exceeded for 1.2.3.4")))
        with self.assertRaises(base.CounterError) as caught:
            cli.PROVIDERS["github.stars"].fetch("octocat/Hello-World", {})
        self.assertIn("rate limit", str(caught.exception))
        self.fake_http(lambda url, headers: (_ for _ in ()).throw(base.HttpError(403, "Must have push access to repository")))
        os.environ["GITHUB_TOKEN"] = "ghp_" + "a" * 36
        self.addCleanup(os.environ.pop, "GITHUB_TOKEN", None)
        with self.assertRaises(base.CounterError) as caught:
            cli.PROVIDERS["github.clones"].fetch("octocat/Hello-World", {})
        self.assertIn("push access", str(caught.exception))


# ------------------------------------------------------------------- mastodon


class Discord(Sandbox):
    INVITE = {"code": "python", "expires_at": None,
              "guild": {"id": "267624335836053506", "name": "Python"},
              "approximate_member_count": 431914, "approximate_presence_count": 32163}

    def test_normalize(self):
        n = discord.normalize_invite
        for raw in ("discord.gg/python", "https://discord.gg/python", "https://discord.gg/python/",
                    "https://discord.com/invite/python", "discordapp.com/invite/python", "https://www.discord.gg/python"):
            self.assertEqual(n(raw), "discord.gg/python", raw)
        self.assertEqual(n("https://discord.gg/aBc-123"), "discord.gg/aBc-123")
        # A bare code is not a target: on its own it could be anything.
        for bad in ("", "python", "dQw4w9WgXcQ", "@omarchy", "octocat/Hello-World", "https://discord.com/channels/1/2",
                    "https://discord.gg/", "https://discord.gg/a/b", "https://discord.com/python", "https://example.com/invite/x"):
            with self.assertRaises(ValueError, msg=bad):
                n(bad)

    def test_detection_offers_both_metrics_and_nothing_else(self):
        for raw in ("https://discord.gg/python", "discord.gg/python", "https://discord.com/invite/python"):
            self.assertEqual([p.id for p in cli.detect_providers(raw)], ["discord.members", "discord.online"], raw)
        self.assertNotIn("discord.members", [p.id for p in cli.detect_providers("dQw4w9WgXcQ")])
        self.assertNotIn("discord.members", [p.id for p in cli.detect_providers("https://mastodon.social/@Gargron")])

    def test_fetch_and_errors(self):
        calls = []

        def fake_http(url, timeout=10, headers=None):
            calls.append(url)
            if "/invites/gone" in url:
                raise base.HttpError(404, "Unknown Invite")
            if "/invites/temp" in url:
                return dict(self.INVITE, expires_at="2026-10-01T00:00:00+00:00")
            if "/invites/group" in url:
                return {"code": "group", "expires_at": None, "channel": {"name": "dm"}}
            return dict(self.INVITE)

        saved = discord.http_json
        discord.http_json = fake_http
        self.addCleanup(setattr, discord, "http_json", saved)
        rows = cli.fetch_all([{"type": "discord.members", "target": "https://discord.gg/python"},
                              {"type": "discord.online", "target": "discord.gg/python"},
                              {"type": "discord.members", "target": "discord.gg/gone"},
                              {"type": "discord.members", "target": "discord.gg/temp"},
                              {"type": "discord.online", "target": "discord.gg/group"}], now=0)["counters"]
        self.assertEqual((rows[0]["value"], rows[0]["name"], rows[0]["url"]), (431914, "Python", "https://discord.gg/python"))
        self.assertEqual(rows[0]["target"], "discord.gg/python")
        self.assertEqual((rows[1]["value"], rows[1]["unit"]), (32163, "online now"))
        self.assertEqual(rows[0]["tooltip"], "Python\n431,914 members")
        self.assertEqual(rows[2]["error"], "invite not found (revoked, expired, or mistyped)")
        self.assertIn("expires (2026-10-01)", rows[3]["error"])
        self.assertIn("does not lead to a server", rows[4]["error"])
        self.assertEqual((rows[0]["group"], rows[0]["groupLabel"], rows[0]["brandColor"]), ("discord", "Discord", "#5865F2"))
        self.assertTrue(all(u.startswith("https://discord.com/api/v10/invites/") and "with_counts=true" in u for u in calls))
        self.assertEqual((rows[0]["minInterval"], rows[0]["effectiveInterval"]), (5, 15))


class Mastodon(Sandbox):
    def test_normalize(self):
        n = mastodon.normalize_account
        for raw in ("Gargron@mastodon.social", "@Gargron@mastodon.social", "https://mastodon.social/@Gargron",
                    "mastodon.social/@Gargron", "https://mastodon.social/@Gargron/12345"):
            self.assertEqual(n(raw), "Gargron@mastodon.social", raw)
        self.assertEqual(n("https://fosstodon.org/users/gnome"), "gnome@fosstodon.org")
        for bad in ("", "Gargron", "@omarchy", "https://www.youtube.com/@omarchy", "youtube.com/@omarchy",
                    "octocat/Hello-World", "https://github.com/o/r", "dQw4w9WgXcQ", "user@nodots"):
            with self.assertRaises(ValueError, msg=bad):
                n(bad)

    def test_detection_offers_both_metrics(self):
        for raw in ("https://mastodon.social/@Gargron", "Gargron@mastodon.social", "@Gargron@mastodon.social"):
            self.assertEqual([p.id for p in cli.detect_providers(raw)], ["mastodon.followers", "mastodon.posts"], raw)
        # And Mastodon never claims the other services' addresses.
        self.assertEqual([p.id for p in cli.detect_providers("@omarchy")], ["youtube.subscribers"])
        self.assertEqual([p.id for p in cli.detect_providers("https://www.youtube.com/@omarchy")], ["youtube.subscribers"])
        self.assertEqual([p.id for p in cli.detect_providers("octocat/Hello-World")][0], "github.stars")

    def test_fetch_and_errors(self):
        saved = mastodon.http_json
        calls = []

        def fake_http(url, timeout=10, headers=None):
            calls.append(url)
            return {"username": "Gargron", "display_name": "Eugen Rochko", "followers_count": 5, "statuses_count": 7,
                    "url": "https://mastodon.social/@Gargron"}

        mastodon.http_json = fake_http
        self.addCleanup(setattr, mastodon, "http_json", saved)
        rows = cli.fetch_all([{"type": "mastodon.followers", "target": "https://mastodon.social/@Gargron"},
                              {"type": "mastodon.posts", "target": "Gargron@mastodon.social"}], now=0)["counters"]
        self.assertEqual(calls, ["https://mastodon.social/api/v1/accounts/lookup?acct=Gargron"] * 2)
        self.assertEqual((rows[0]["value"], rows[0]["label"], rows[0]["unit"]), (5, "Eugen Rochko", "followers"))
        self.assertEqual((rows[1]["value"], rows[1]["unit"], rows[1]["effectiveInterval"]), (7, "posts", 15))
        self.assertEqual(rows[0]["brandColor"], "#6364FF")
        self.assertEqual(rows[0]["url"], "https://mastodon.social/@Gargron")
        mastodon.http_json = lambda url, timeout=10, headers=None: (_ for _ in ()).throw(base.HttpError(404, "Record not found"))
        with self.assertRaises(base.CounterError) as caught:
            cli.PROVIDERS["mastodon.followers"].fetch("nobody@mastodon.social", {})
        self.assertEqual(str(caught.exception), "no account nobody on mastodon.social")

    def test_tag_normalize_and_detection(self):
        n = mastodon.normalize_tag
        for raw in ("#TuneTuesday@mastodon.social", "https://mastodon.social/tags/TuneTuesday", "mastodon.social/tags/TuneTuesday"):
            self.assertEqual(n(raw), "#TuneTuesday@mastodon.social", raw)
        for bad in ("", "TuneTuesday", "#TuneTuesday", "Gargron@mastodon.social", "https://mastodon.social/@Gargron",
                    "https://www.youtube.com/tags/x", "#bad tag@mastodon.social"):
            with self.assertRaises(ValueError, msg=bad):
                n(bad)
        self.assertEqual([p.id for p in cli.detect_providers("https://mastodon.social/tags/TuneTuesday")], ["mastodon.tag", "mastodon.tagpeople"])
        self.assertEqual([p.id for p in cli.detect_providers("#TuneTuesday@mastodon.social")], ["mastodon.tag", "mastodon.tagpeople"])
        # Accounts and tags never claim each other.
        self.assertEqual([p.id for p in cli.detect_providers("Gargron@mastodon.social")], ["mastodon.followers", "mastodon.posts"])
        with self.assertRaises(ValueError):
            mastodon.normalize_account("#TuneTuesday@mastodon.social")

    def test_tag_fetch_sums_the_week(self):
        saved = mastodon.http_json
        mastodon.http_json = lambda url, timeout=10, headers=None: {
            "name": "tunetuesday", "url": "https://mastodon.social/tags/tunetuesday",
            "history": [{"day": "1", "uses": "62", "accounts": "38"}, {"day": "2", "uses": "0", "accounts": "0"}, {"day": "3", "uses": "6", "accounts": "4"}]}
        self.addCleanup(setattr, mastodon, "http_json", saved)
        rows = cli.fetch_all([{"type": "mastodon.tag", "target": "https://mastodon.social/tags/TuneTuesday"},
                              {"type": "mastodon.tagpeople", "target": "#TuneTuesday@mastodon.social"}], now=0)["counters"]
        self.assertEqual((rows[0]["value"], rows[0]["label"], rows[0]["unit"]), (68, "#tunetuesday", "posts this week"))
        self.assertEqual((rows[1]["value"], rows[1]["unit"]), (42, "people this week"))
        self.assertEqual(rows[0]["url"], "https://mastodon.social/tags/TuneTuesday")  # the provider's URL keeps the casing
        self.assertEqual(rows[0]["tooltip"], "#tunetuesday\n68 posts this week")


# ---------------------------------------------------------------------- fetch


class History(unittest.TestCase):
    def test_deltas(self):
        today = dt.date(2026, 9, 21)
        history = {"2026-09-20": 100, "2026-09-14": 60, "2026-09-10": 10, "2026-09-21": 105}
        self.assertEqual(cli.history_deltas(history, 112, today), (12, 52))

    def test_no_history(self):
        self.assertEqual(cli.history_deltas({}, 5, dt.date(2026, 9, 21)), (None, None))
        self.assertEqual(cli.history_deltas({"2026-09-21": 3}, 5, dt.date(2026, 9, 21)), (None, None))

    def test_prune(self):
        today = dt.date(2026, 9, 21)
        kept = cli.prune_history({"2026-01-01": 1, "2026-09-01": 2, "bad": "x"}, today)
        self.assertEqual(kept, {"2026-09-01": 2})


class Fetch(Sandbox):
    def test_report_shape_and_cache(self):
        calls = []

        def subs(target, secrets):
            calls.append(target)
            return cli.Result(1234, "Omarchy", "https://www.youtube.com/@omarchy")

        self.fake("youtube.subscribers", subs)
        counters = [{"type": "youtube.subscribers", "target": "https://www.youtube.com/@omarchy", "color": "accent", "glyphColor": "urgent"}]

        report = cli.fetch_all(counters, max_age_minutes=15, now=1_000_000)
        row = report["counters"][0]
        self.assertTrue(report["configured"])
        self.assertEqual(row["target"], "@omarchy")
        self.assertEqual(row["value"], 1234)
        self.assertEqual(row["label"], "Omarchy")
        self.assertEqual(row["color"], "accent")
        self.assertEqual(row["glyphColor"], "urgent")
        self.assertEqual(row["textColor"], "")
        self.assertEqual(row["brandColor"], "#FF0000")
        self.assertEqual(row["brandTextColor"], "")
        self.assertEqual((row["group"], row["groupLabel"]), ("youtube", "YouTube"))
        self.assertIs(row["bar"], True)
        hidden = cli.fetch_all([{"type": "youtube.subscribers", "target": "@omarchy", "bar": False}], now=1_000_000)["counters"][0]
        self.assertIs(hidden["bar"], False)
        self.assertEqual(row["credential"], "youtube")
        self.assertEqual(row["unit"], "subscribers")
        self.assertEqual(row["minInterval"], 1)
        self.assertEqual(row["effectiveInterval"], 15)
        self.assertFalse(row["rateLimited"])
        self.assertIsNone(row["error"])
        self.assertEqual(row["url"], "https://www.youtube.com/@omarchy")
        self.assertEqual(row["tooltip"], "Omarchy\n1,234 subscribers")
        self.assertEqual(calls, ["@omarchy"])

        # Within max-age: served from the cache, no second fetch.
        report = cli.fetch_all(counters, max_age_minutes=15, now=1_000_000 + 60)
        self.assertEqual(report["counters"][0]["value"], 1234)
        self.assertEqual(calls, ["@omarchy"])

        # Past max-age: fetched again. --force also fetches (past the 1-minute cap).
        cli.fetch_all(counters, max_age_minutes=15, now=1_000_000 + 16 * 60)
        self.assertEqual(len(calls), 2)
        cli.fetch_all(counters, max_age_minutes=15, force=True, now=1_000_000 + 18 * 60)
        self.assertEqual(len(calls), 3)

    def test_per_counter_interval_wins(self):
        calls = []
        self.fake("youtube.likes", lambda t, s: (calls.append(t), cli.Result(7, "Vid"))[1])
        counters = [{"type": "youtube.likes", "target": "dQw4w9WgXcQ", "interval": 60}]
        cli.fetch_all(counters, max_age_minutes=1, now=0)
        cli.fetch_all(counters, max_age_minutes=1, now=30 * 60)
        self.assertEqual(len(calls), 1)
        cli.fetch_all(counters, max_age_minutes=1, now=61 * 60)
        self.assertEqual(len(calls), 2)

    def test_rate_cap_beats_everything(self):
        calls = []
        self.fake("github.stars", lambda t, s: (calls.append(t), cli.Result(3, "r"))[1])
        counters = [{"type": "github.stars", "target": "o/r", "interval": 1}]  # below the 5-minute cap
        row = cli.fetch_all(counters, max_age_minutes=1, now=0)["counters"][0]
        self.assertEqual(row["effectiveInterval"], 5)
        self.assertEqual(len(calls), 1)
        row = cli.fetch_all(counters, max_age_minutes=1, now=2 * 60)["counters"][0]
        self.assertEqual(len(calls), 1)
        self.assertFalse(row["rateLimited"], "not due yet is not the same as refused")
        self.assertEqual(row["value"], 3)
        self.assertTrue(row["nextFetchAt"])
        row = cli.fetch_all(counters, max_age_minutes=1, force=True, now=3 * 60)["counters"][0]
        self.assertEqual(len(calls), 1, "a forced fetch inside the cap serves the cache")
        self.assertTrue(row["rateLimited"])
        cli.fetch_all(counters, max_age_minutes=1, force=True, now=5 * 60 + 1)
        self.assertEqual(len(calls), 2)

    def test_interval_setting_respects_cap(self):
        counter = {"type": "github.stars", "target": "o/r"}
        with self.assertRaises(ValueError) as caught:
            cli.apply_setting(counter, "interval", "1")
        self.assertIn("at most every 5 minutes", str(caught.exception))
        self.assertIn("60 requests", str(caught.exception))
        cli.apply_setting(counter, "interval", "10")
        self.assertEqual(counter["interval"], 10)
        cli.apply_setting({"type": "youtube.likes", "target": "dQw4w9WgXcQ"}, "interval", "1")

    def test_error_keeps_last_value_and_backs_off(self):
        state = {"ok": True}

        def flaky(target, secrets):
            if state["ok"]:
                return cli.Result(50, "Vid")
            raise cli.CounterError("YouTube API daily quota exceeded")

        self.fake("youtube.likes", flaky)
        counters = [{"type": "youtube.likes", "target": "dQw4w9WgXcQ", "label": "Mine"}]
        cli.fetch_all(counters, max_age_minutes=1, now=0)
        state["ok"] = False
        row = cli.fetch_all(counters, max_age_minutes=1, now=120)["counters"][0]
        self.assertEqual(row["value"], 50)
        self.assertEqual(row["error"], "YouTube API daily quota exceeded")
        self.assertEqual(row["label"], "Mine")
        self.assertEqual(row["tooltip"], "Mine\n50 likes\nstale: YouTube API daily quota exceeded")
        # The row says when it is tried again: the backoff after the failed attempt.
        self.assertEqual(row["nextFetchAt"], cli.iso_at(120 + cli.ERROR_RETRY_MINUTES * 60))
        # Retried only after the backoff; meanwhile the row keeps naming that time.
        state["ok"] = True
        row = cli.fetch_all(counters, max_age_minutes=1, now=180)["counters"][0]
        self.assertEqual(row["error"], "YouTube API daily quota exceeded")
        self.assertEqual(row["nextFetchAt"], cli.iso_at(120 + cli.ERROR_RETRY_MINUTES * 60))
        row = cli.fetch_all(counters, max_age_minutes=1, now=120 + cli.ERROR_RETRY_MINUTES * 60 + 1)["counters"][0]
        self.assertIsNone(row["error"])

    def test_never_fetched_failure_names_its_retry(self):
        self.fake("youtube.likes", lambda t, s: (_ for _ in ()).throw(cli.CounterError("video not found")))
        counters = [{"type": "youtube.likes", "target": "dQw4w9WgXcQ"}]
        row = cli.fetch_all(counters, max_age_minutes=1, now=1000)["counters"][0]
        self.assertIsNone(row["value"])
        self.assertEqual(row["nextFetchAt"], cli.iso_at(1000 + cli.ERROR_RETRY_MINUTES * 60))
        row = cli.fetch_all(counters, max_age_minutes=1, now=1030)["counters"][0]
        self.assertEqual(row["nextFetchAt"], cli.iso_at(1000 + cli.ERROR_RETRY_MINUTES * 60))

    def test_provider_bug_is_contained(self):
        self.fake("youtube.likes", lambda t, s: 1 / 0)
        self.fake("youtube.subscribers", lambda t, s: cli.Result(9, "Chan"))
        counters = [{"type": "youtube.likes", "target": "dQw4w9WgXcQ"}, {"type": "youtube.subscribers", "target": "@xyz"}]
        rows = cli.fetch_all(counters, now=0)["counters"]
        self.assertIn("ZeroDivisionError", rows[0]["error"])
        self.assertEqual(rows[1]["value"], 9)

    def test_bad_config_rows(self):
        rows = cli.fetch_all([{"type": "nope.metric", "target": "x"}, {"type": "youtube.likes", "target": "short"}], now=0)["counters"]
        self.assertIn("unknown counter type", rows[0]["error"])
        self.assertIn("11 characters", rows[1]["error"])
        self.assertIsNone(rows[0]["value"])
        self.assertEqual(rows[0]["tooltip"], "nope.metric\nunknown counter type 'nope.metric'")

    def test_no_key_is_a_row_error(self):
        os.environ.pop("YOUTUBE_API_KEY", None)
        row = cli.fetch_all([{"type": "youtube.likes", "target": "dQw4w9WgXcQ"}], now=0)["counters"][0]
        self.assertIn("no YouTube API key", row["error"])
        self.assertIn("auth youtube set", row["error"])

    def test_stale_cache_entries_are_dropped(self):
        self.fake("youtube.likes", lambda t, s: cli.Result(1, "A"))
        cli.fetch_all([{"type": "youtube.likes", "target": "dQw4w9WgXcQ"}], now=0)
        cli.fetch_all([], now=1)
        self.assertEqual(cli.load_state()["counters"], {})

    def test_history_written(self):
        self.fake("youtube.likes", lambda t, s: cli.Result(42, "A"))
        cli.fetch_all([{"type": "youtube.likes", "target": "dQw4w9WgXcQ"}], now=0)
        entry = cli.load_state()["counters"]["youtube.likes:dQw4w9WgXcQ"]
        self.assertEqual(list(entry["history"].values()), [42])
        self.assertEqual(entry["url"], "https://www.youtube.com/watch?v=dQw4w9WgXcQ")


class Tooltip(unittest.TestCase):
    def test_matches_model_js(self):
        counters = [
            {"label": "Chan", "value": 1234, "unit": "subscribers", "error": None, "deltaDay": 4},
            {"label": "Vid", "value": None, "unit": "likes", "error": "no key", "deltaDay": None},
            {"label": "Old", "value": 10, "unit": "likes", "error": "quota", "deltaDay": None},
        ]
        self.assertEqual(base.default_tooltip(counters[0]), "Chan\n1,234 subscribers  ·  +4 today")
        self.assertEqual(base.default_tooltip(counters[1]), "Vid\nno key")
        self.assertEqual(base.default_tooltip(counters[2]), "Old\n10 likes\nstale: quota")
        self.assertEqual(base.signed(-3), "−3")
        self.assertEqual(base.signed(0), "±0")

    def test_label_is_clipped_like_model_js(self):
        self.assertEqual(base.TOOLTIP_LABEL_MAX, 40)
        self.assertEqual(base.clip("short"), "short")
        self.assertEqual(base.clip("x" * 41), "x" * 39 + "…")
        self.assertEqual(base.clip("Syncing the Akai Sample with Your DAW in 2026", 20), "Syncing the Akai Sa…")
        self.assertEqual(base.clip("a b c d e f g h i j k", 10), "a b c d e…")
        row = {"label": "L" * 50, "value": 1, "unit": "x", "error": None, "deltaDay": None}
        self.assertEqual(base.default_tooltip(row), "L" * 39 + "…\n1 x")


# ----------------------------------------------------------------- shell.json


class ShellJson(Sandbox):
    def test_read_counters(self):
        self.write_shell(present=False)
        self.assertIsNone(cli.read_counters())
        self.write_shell()
        self.assertEqual(cli.read_counters(), [])
        self.write_shell([{"type": "youtube.likes", "target": "dQw4w9WgXcQ"}, "junk"])
        self.assertEqual(cli.read_counters(), [{"type": "youtube.likes", "target": "dQw4w9WgXcQ"}])

    def test_write_counters(self):
        self.write_shell([])
        cli.write_counters([{"type": "youtube.likes", "target": "dQw4w9WgXcQ"}])
        self.assertEqual(cli.read_counters(), [{"type": "youtube.likes", "target": "dQw4w9WgXcQ"}])
        with open(cli.SHELL_JSON) as fh:
            self.assertEqual(json.load(fh)["bar"]["layout"]["left"], [{"id": "omarchy.menu"}])

    def test_write_counters_without_entry(self):
        self.write_shell(present=False)
        with self.assertRaises(cli.CounterError):
            cli.write_counters([])


class SetCommand(unittest.TestCase):
    def test_find_counter(self):
        counters = [{"type": "youtube.likes", "target": "dQw4w9WgXcQ"}, {"type": "youtube.subscribers", "target": "@omarchy"}]
        self.assertEqual(cli.find_counter(counters, "2"), 1)
        self.assertEqual(cli.find_counter(counters, "@omarchy"), 1)
        self.assertEqual(cli.find_counter(counters, "youtube.likes:dQw4w9WgXcQ"), 0)
        self.assertIsNone(cli.find_counter(counters, "3"))
        self.assertIsNone(cli.find_counter(counters, "0"))
        self.assertIsNone(cli.find_counter(counters, "nope"))

    def test_apply_setting_values(self):
        c = {"type": "youtube.subscribers", "target": "@omarchy"}
        cli.apply_setting(c, "glyphColor", "#FF0000")
        cli.apply_setting(c, "textColor", "Accent")
        cli.apply_setting(c, "style", "long")
        cli.apply_setting(c, "interval", "30")
        cli.apply_setting(c, "label", "Chan")
        cli.apply_setting(c, "icon", "\U000F05C3")
        cli.apply_setting(c, "target", "https://www.youtube.com/@omarchy/videos")
        self.assertEqual(c, {"type": "youtube.subscribers", "target": "@omarchy", "glyphColor": "#FF0000",
                             "textColor": "accent", "style": "long", "interval": 30, "label": "Chan", "icon": "\U000F05C3"})
        cli.apply_setting(c, "glyphColor", "")
        cli.apply_setting(c, "interval", " ")
        self.assertNotIn("glyphColor", c)
        self.assertNotIn("interval", c)
        # bar: off is stored, on is the default and therefore removed.
        cli.apply_setting(c, "bar", "off")
        self.assertIs(c["bar"], False)
        cli.apply_setting(c, "bar", "show")
        self.assertNotIn("bar", c)
        cli.apply_setting(c, "bar", "false")
        cli.apply_setting(c, "bar", "")
        self.assertNotIn("bar", c)
        with self.assertRaises(ValueError):
            cli.apply_setting(c, "bar", "maybe")

    def test_apply_setting_rejects(self):
        c = {"type": "youtube.likes", "target": "dQw4w9WgXcQ"}
        for key, value in (("style", "huge"), ("color", "reddish"), ("color", "#12"), ("interval", "0"),
                           ("interval", "soon"), ("target", ""), ("target", "short"), ("type", "youtube.views"), ("bogus", "x")):
            with self.assertRaises(ValueError, msg="%s=%s" % (key, value)):
                cli.apply_setting(dict(c), key, value)


class IntervalNote(unittest.TestCase):
    def test_reasons(self):
        base = {"minInterval": 1, "defaultInterval": None, "interval": None}
        self.assertEqual(cli.interval_note(base, 15), "every 15 min")
        self.assertEqual(cli.interval_note(dict(base, interval=30), 15), "every 30 min (own)")
        self.assertEqual(cli.interval_note(dict(base, defaultInterval=60, minInterval=15), 15), "every 60 min (source)")
        # A cap raises what was asked, from the widget or the counter.
        self.assertEqual(cli.interval_note(dict(base, minInterval=5), 1), "every 5 min (cap)")
        self.assertEqual(cli.interval_note(dict(base, minInterval=5, interval=2), 15), "every 5 min (cap)")
        self.assertEqual(cli.interval_note(dict(base, minInterval=5), 15), "every 15 min")
        self.assertEqual(cli.interval_note({"type": "nope.metric"}, 15), "")
        self.assertEqual(cli.interval_note(base, None), "every %d min" % cli.DEFAULT_INTERVAL_MINUTES)


class Defaults(Sandbox):
    def test_fill_defaults(self):
        c = {"type": "youtube.subscribers", "target": "@a"}
        self.assertEqual(cli.fill_defaults(c), ["icon", "glyphColor"])
        self.assertEqual(c["icon"], cli.PROVIDERS["youtube.subscribers"].icon)
        self.assertEqual(c["glyphColor"], "#FF0000")
        self.assertNotIn("textColor", c)
        # Own values are kept; a `color` keeps the separate colours out.
        c = {"type": "github.stars", "target": "o/r", "icon": "x", "color": "accent"}
        self.assertEqual(cli.fill_defaults(c), [])
        self.assertEqual(c, {"type": "github.stars", "target": "o/r", "icon": "x", "color": "accent"})
        self.assertEqual(cli.fill_defaults({"type": "nope.metric", "target": "x"}), [])

    def test_color_replaces_the_separate_colours(self):
        c = {"type": "github.stars", "target": "o/r", "glyphColor": "#E3B341", "textColor": "muted"}
        cli.apply_setting(c, "color", "accent")
        self.assertEqual(c, {"type": "github.stars", "target": "o/r", "color": "accent"})

    def test_fill_command(self):
        self.write_shell([{"type": "github.stars", "target": "o/r"}, {"type": "github.issues", "target": "o/r", "glyphColor": "urgent"}])
        code, out = self.run_cli(["fill"])
        self.assertEqual(code, 0)
        self.assertIn("Filled 2 counters", out)
        stars, issues = cli.read_counters()
        self.assertEqual(stars["glyphColor"], "#E3B341")
        self.assertEqual(stars["icon"], cli.PROVIDERS["github.stars"].icon)
        self.assertEqual(issues["glyphColor"], "urgent")   # kept
        self.assertEqual(issues["icon"], cli.PROVIDERS["github.issues"].icon)
        code, out = self.run_cli(["fill"])
        self.assertIn("already", out)


class MoveCommand(Sandbox):
    ROWS = [
        {"type": "youtube.subscribers", "target": "@a"},
        {"type": "github.stars", "target": "o/r1"},
        {"type": "youtube.likes", "target": "v2"},
        {"type": "mastodon.followers", "target": "u@m.social"},
        {"type": "github.issues", "target": "o/r2"},
        {"type": "bogus.type", "target": "x"},
    ]

    @staticmethod
    def targets(counters):
        return [c["target"] for c in counters]

    def test_group_rows(self):
        self.assertEqual(cli.group_rows(self.ROWS), [("youtube", [0, 2]), ("github", [1, 4]), ("mastodon", [3]), ("other", [5])])
        self.assertEqual(cli.group_rows([]), [])
        self.assertEqual(self.targets(cli.in_panel_order(self.ROWS)), ["@a", "v2", "o/r1", "o/r2", "u@m.social", "x"])

    def test_read_counters_in_panel_order(self):
        # A hand-written, interleaved list is numbered the way the panel shows it.
        self.write_shell([dict(c) for c in self.ROWS])
        self.assertEqual(self.targets(cli.read_counters()), ["@a", "v2", "o/r1", "o/r2", "u@m.social", "x"])
        self.assertEqual(cli.find_counter(cli.read_counters(), "3"), 2)
        self.assertEqual(cli.read_counters()[2]["target"], "o/r1")

    def test_move_counter_within_group(self):
        rows = self.ROWS
        # The result is in panel order: groups together, the moved one shifted.
        self.assertEqual(self.targets(cli.move_counter(rows, 2, "up")), ["v2", "@a", "o/r1", "o/r2", "u@m.social", "x"])
        self.assertEqual(self.targets(cli.move_counter(rows, 4, "top")), ["@a", "v2", "o/r2", "o/r1", "u@m.social", "x"])
        self.assertEqual(self.targets(cli.move_counter(rows, 0, "bottom")), ["v2", "@a", "o/r1", "o/r2", "u@m.social", "x"])
        self.assertIsNone(cli.move_counter(rows, 0, "up"))
        self.assertIsNone(cli.move_counter(rows, 2, "down"))
        self.assertIsNone(cli.move_counter(rows, 3, "up"))
        self.assertIsNone(cli.move_counter(rows, 9, "up"))
        self.assertEqual(rows, self.ROWS)  # never in place

    def test_move_group(self):
        rows = self.ROWS
        self.assertEqual(self.targets(cli.move_group(rows, "github", "up")), ["o/r1", "o/r2", "@a", "v2", "u@m.social", "x"])
        self.assertEqual(self.targets(cli.move_group(rows, "mastodon", "top")), ["u@m.social", "@a", "v2", "o/r1", "o/r2", "x"])
        self.assertEqual(self.targets(cli.move_group(rows, "youtube", "bottom")), ["o/r1", "o/r2", "u@m.social", "x", "@a", "v2"])
        self.assertIsNone(cli.move_group(rows, "youtube", "up"))
        self.assertIsNone(cli.move_group(rows, "other", "down"))
        self.assertIsNone(cli.move_group(rows, "nope", "up"))

    def test_find_group(self):
        self.assertEqual(cli.find_group(self.ROWS, "github"), "github")
        self.assertEqual(cli.find_group(self.ROWS, "GitHub"), "github")
        self.assertEqual(cli.find_group(self.ROWS, "YouTube"), "youtube")
        self.assertEqual(cli.find_group(self.ROWS, "other"), "other")
        self.assertIsNone(cli.find_group(self.ROWS, "bluesky"))
        self.assertIsNone(cli.find_group(self.ROWS, ""))

    def test_command(self):
        self.write_shell([dict(c) for c in self.ROWS])
        # Numbers are panel positions: 2 is v2 (the second YouTube counter).
        code, out = self.run_cli(["move", "2", "up"])
        self.assertEqual(code, 0)
        self.assertIn("Moved youtube.likes v2 up", out)
        self.assertEqual(self.targets(cli.read_counters()), ["v2", "@a", "o/r1", "o/r2", "u@m.social", "x"])
        with open(cli.SHELL_JSON) as fh:
            stored = json.load(fh)["bar"]["layout"]["right"][0]["counters"]
        self.assertEqual(self.targets(stored), ["v2", "@a", "o/r1", "o/r2", "u@m.social", "x"])
        code, out = self.run_cli(["move", "github", "top"])
        self.assertIn("Moved the GitHub group top", out)
        self.assertEqual(self.targets(cli.read_counters()), ["o/r1", "o/r2", "v2", "@a", "u@m.social", "x"])
        # A target names a counter; a no-op says so and changes nothing.
        code, out = self.run_cli(["move", "o/r1", "up"])
        self.assertIn("already at the top", out)
        self.assertEqual(self.targets(cli.read_counters()), ["o/r1", "o/r2", "v2", "@a", "u@m.social", "x"])
        with self.assertRaises(SystemExit):
            self.run_cli(["move", "nothing", "up"])


# ---------------------------------------------------------------- credentials


class Credentials(Sandbox):
    def test_resolution_order(self):
        cred = youtube.CREDENTIAL
        os.environ.pop("YOUTUBE_API_KEY", None)
        with self.assertRaises(cli.CounterError) as caught:
            cred.resolve({})
        self.assertIn("no YouTube API key", str(caught.exception))
        self.assertIn("auth youtube set", str(caught.exception))
        self.assertFalse(cred.present({}))
        os.environ["YOUTUBE_API_KEY"] = "env-key-0123456789abcdef"
        self.addCleanup(os.environ.pop, "YOUTUBE_API_KEY", None)
        self.assertEqual(cred.resolve({}), "env-key-0123456789abcdef")
        self.assertTrue(cred.present({}))
        self.assertEqual(cred.resolve({"youtube": {"apiKey": " file-key-0123456789abcdef "}}), "file-key-0123456789abcdef")

    def test_store_keeps_the_old_layout(self):
        secrets = {}
        youtube.CREDENTIAL.store(secrets, "x")
        self.assertEqual(secrets, {"youtube": {"apiKey": "x"}})
        cli.save_secrets(secrets)
        self.assertEqual(oct(os.stat(cli.SECRETS_PATH).st_mode & 0o777), "0o600")
        self.assertEqual(cli.load_secrets(), {"youtube": {"apiKey": "x"}})
        youtube.CREDENTIAL.clear(secrets)
        self.assertEqual(secrets, {})
        self.assertEqual(youtube.CREDENTIAL.masked("AIzaSyABCDEFGHIJKLMNOP"), "AIzaSy…MNOP")

    def test_auth_command_and_key_alias(self):
        youtube.YouTubeKey.verify = lambda self, value: None
        self.write_shell([{"type": "youtube.likes", "target": "dQw4w9WgXcQ"}])
        os.environ.pop("YOUTUBE_API_KEY", None)
        # The key is never taken from the command line: piped in instead.
        with self.assertRaises(SystemExit):
            self.run_cli(["auth", "youtube", "set", "k" * 30])
        with self.assertRaises(SystemExit) as caught:
            self.run_cli(["auth", "youtube", "set"])   # no terminal in a test, no --stdin
        self.assertEqual(caught.exception.code, 64)
        saved_stdin = sys.stdin
        sys.stdin = io.StringIO("k" * 30 + "\n")
        try:
            code, out = self.run_cli(["auth", "youtube", "set", "--stdin"])
        finally:
            sys.stdin = saved_stdin
        self.assertEqual(code, 0)
        self.assertEqual(cli.load_secrets(), {"youtube": {"apiKey": "k" * 30}})
        code, out = self.run_cli(["auth", "youtube", "show"])
        self.assertIn("kkkkkk…kkkk", out)
        code, out = self.run_cli(["auth"])
        self.assertIn("used by 1 counter", out)
        self.assertIn("github", out)
        code, out = self.run_cli(["key"])
        self.assertIn("kkkkkk…kkkk", out)
        code, out = self.run_cli(["key", "clear"])
        self.assertEqual(cli.load_secrets(), {})
        with self.assertRaises(SystemExit) as caught:
            self.run_cli(["auth", "nope", "show"])
        self.assertEqual(caught.exception.code, 64)


# ------------------------------------------------------------------ hardening


class Hardening(Sandbox):
    def test_trusted_tool_ignores_the_users_path(self):
        # A helper is found only in the system directories, root-owned.
        sh = base.trusted_tool("sh")
        self.assertIn(sh, ("/usr/local/bin/sh", "/usr/bin/sh", "/bin/sh"))
        self.assertTrue(base.trusted_file(sh))
        planted = os.path.join(self.tmp, "gh")
        with open(planted, "w") as fh:
            fh.write("#!/bin/sh\necho stolen\n")
        os.chmod(planted, 0o755)
        saved = os.environ.get("PATH", "")
        os.environ["PATH"] = self.tmp + ":" + saved
        self.addCleanup(os.environ.__setitem__, "PATH", saved)
        self.assertEqual(shutil.which("gh"), planted)
        base._TOOL_CACHE.clear()
        self.assertNotEqual(base.trusted_tool("gh"), planted)
        self.assertIsNone(base.trusted_tool("no-such-helper-xyz"))
        self.assertFalse(base.trusted_file(planted))

    def test_minimal_env(self):
        os.environ["LD_PRELOAD"] = "/tmp/evil.so"
        os.environ["HOME"] = "/home/someone"
        self.addCleanup(os.environ.pop, "LD_PRELOAD", None)
        env = base.minimal_env(("GH_CONFIG_DIR",))
        self.assertEqual(env["PATH"], "/usr/local/bin:/usr/bin:/bin")
        self.assertEqual(env["HOME"], "/home/someone")
        self.assertNotIn("LD_PRELOAD", env)
        self.assertNotIn("SSL_CERT_FILE", env)

    def test_only_https_and_https_redirects(self):
        with self.assertRaises(cli.CounterError):
            base.http_json("http://api.github.com/repos/o/r")
        handler = base.HttpsOnlyRedirects()
        req = urllib.request.Request("https://example.test/a")
        with self.assertRaises(cli.CounterError):
            handler.redirect_request(req, None, 302, "Found", {}, "http://example.test/b")
        moved = handler.redirect_request(req, None, 302, "Found", {}, "https://example.test/b")
        self.assertEqual(moved.full_url, "https://example.test/b")
        self.assertEqual(base.MAX_REDIRECTS, 3)

    def test_errors_are_scrubbed_of_credentials(self):
        self.assertEqual(base.scrub("key AIzaSyEXAMPLEKEY0123 rejected", ["AIzaSyEXAMPLEKEY0123"]), "key ••• rejected")
        self.assertEqual(base.scrub("short", ["ab"]), "short")   # a tiny value would blank real words
        os.environ["YOUTUBE_API_KEY"] = "secret-key-0123456789"
        self.addCleanup(os.environ.pop, "YOUTUBE_API_KEY", None)
        self.fake("youtube.likes", lambda t, s: (_ for _ in ()).throw(cli.CounterError("bad request for key=secret-key-0123456789")))
        row = cli.fetch_all([{"type": "youtube.likes", "target": "dQw4w9WgXcQ"}], now=0)["counters"][0]
        self.assertEqual(row["error"], "bad request for key=•••")
        self.assertNotIn("secret-key", row["tooltip"])

    def test_secrets_and_state_are_not_read_through_a_symlink(self):
        elsewhere = os.path.join(self.tmp, "elsewhere.json")
        with open(elsewhere, "w") as fh:
            json.dump({"youtube": {"apiKey": "k" * 30}}, fh)
        os.makedirs(os.path.dirname(cli.SECRETS_PATH), exist_ok=True)
        os.symlink(elsewhere, cli.SECRETS_PATH)
        self.assertEqual(cli.load_secrets(), {})
        os.unlink(cli.SECRETS_PATH)
        cli.save_secrets({"youtube": {"apiKey": "k" * 30}})
        self.assertEqual(cli.load_secrets(), {"youtube": {"apiKey": "k" * 30}})

    def test_add_does_not_enable_the_widget_unasked(self):
        self.write_shell(present=False)
        with self.assertRaises(SystemExit):
            self.run_cli(["add", "github.stars", "octocat/Hello-World", "--no-verify"])


# ----------------------------------------------------------------------- live


@unittest.skipUnless(os.environ.get("YOUTUBE_API_KEY"), "YOUTUBE_API_KEY not set")
class LiveYouTube(unittest.TestCase):
    def test_subscribers(self):
        result = cli.PROVIDERS["youtube.subscribers"].fetch("@youtube", {})
        self.assertGreater(result.value, 1_000_000)
        self.assertTrue(result.name)

    def test_likes(self):
        result = cli.PROVIDERS["youtube.likes"].fetch("dQw4w9WgXcQ", {})
        self.assertGreater(result.value, 1_000_000)

    def test_views(self):
        result = cli.PROVIDERS["youtube.views"].fetch("dQw4w9WgXcQ", {})
        self.assertGreater(result.value, 1_000_000_000)
        self.assertEqual(result.url, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    def test_key_is_accepted(self):
        youtube.CREDENTIAL.verify(os.environ["YOUTUBE_API_KEY"])

    def test_rejected_key_is_reported(self):
        with self.assertRaises(cli.CounterError) as caught:
            youtube.CREDENTIAL.verify("AIzaNotARealKey0000000000000000000000")
        self.assertIn("rejected", str(caught.exception))

    def test_missing_channel_and_video(self):
        with self.assertRaises(cli.CounterError) as caught:
            cli.PROVIDERS["youtube.subscribers"].fetch("@no-such-channel-xyz-987654", {})
        self.assertIn("not found", str(caught.exception))
        with self.assertRaises(cli.CounterError) as caught:
            cli.PROVIDERS["youtube.likes"].fetch("zzzzzzzzzzz", {})
        self.assertIn("not found", str(caught.exception))

    def test_end_to_end_report(self):
        # The fetch loop as the panel runs it: cache in a temp dir, one key
        # from the environment, a report row per counter.
        tmp = tempfile.mkdtemp(prefix="omacounter-live-")
        self.addCleanup(shutil.rmtree, tmp)
        saved = cli.STATE_PATH, cli.SECRETS_PATH
        cli.STATE_PATH, cli.SECRETS_PATH = os.path.join(tmp, "state.json"), os.path.join(tmp, "secrets.json")
        self.addCleanup(lambda: setattr(cli, "STATE_PATH", saved[0]) or setattr(cli, "SECRETS_PATH", saved[1]))
        counters = [{"type": "youtube.subscribers", "target": "@youtube", "label": "YT"}]
        rows = cli.fetch_all(counters, max_age_minutes=15, force=True)["counters"]
        self.assertIsNone(rows[0]["error"])
        self.assertGreater(rows[0]["value"], 1_000_000)
        self.assertEqual(rows[0]["tooltip"].split("\n")[0], "YT")
        self.assertNotIn(os.environ["YOUTUBE_API_KEY"], json.dumps(rows))
        # A second run inside the rate cap is served from the cache.
        again = cli.fetch_all(counters, max_age_minutes=15, force=True)["counters"]
        self.assertTrue(again[0]["rateLimited"])
        self.assertEqual(again[0]["value"], rows[0]["value"])


@unittest.skipUnless(os.environ.get("OMACOUNTER_LIVE"), "OMACOUNTER_LIVE not set")
class LiveKeyless(unittest.TestCase):
    def test_github_stars(self):
        result = cli.PROVIDERS["github.stars"].fetch("octocat/Hello-World", {})
        self.assertGreater(result.value, 1000)
        self.assertEqual(result.name, "octocat/Hello-World")

    def test_github_issues_and_pulls(self):
        issues = cli.PROVIDERS["github.issues"].fetch("octocat/Hello-World", {})
        pulls = cli.PROVIDERS["github.pulls"].fetch("octocat/Hello-World", {})
        self.assertGreaterEqual(issues.value, 0)
        self.assertGreaterEqual(pulls.value, 0)
        self.assertEqual(issues.url, "https://github.com/octocat/Hello-World/issues")

    def test_github_missing_repo(self):
        with self.assertRaises(cli.CounterError) as caught:
            cli.PROVIDERS["github.stars"].fetch("octocat/no-such-repo-987654", {})
        self.assertIn("not found", str(caught.exception))

    def test_mastodon(self):
        result = cli.PROVIDERS["mastodon.followers"].fetch("Gargron@mastodon.social", {})
        self.assertGreater(result.value, 100_000)
        self.assertTrue(result.name)
        posts = cli.PROVIDERS["mastodon.posts"].fetch("Gargron@mastodon.social", {})
        self.assertGreater(posts.value, 1000)

    def test_mastodon_missing_account(self):
        with self.assertRaises(cli.CounterError) as caught:
            cli.PROVIDERS["mastodon.followers"].fetch("nosuchaccountxyz987654@mastodon.social", {})
        self.assertIn("no account", str(caught.exception))

    def test_mastodon_tag(self):
        result = cli.PROVIDERS["mastodon.tag"].fetch("#TuneTuesday@mastodon.social", {})
        self.assertGreaterEqual(result.value, 0)
        self.assertEqual(result.name.lower(), "#tunetuesday")
        people = cli.PROVIDERS["mastodon.tagpeople"].fetch("#TuneTuesday@mastodon.social", {})
        self.assertGreaterEqual(people.value, 0)

    def test_discord(self):
        members = cli.PROVIDERS["discord.members"].fetch("discord.gg/python", {})
        online = cli.PROVIDERS["discord.online"].fetch("discord.gg/python", {})
        self.assertGreater(members.value, 100_000)
        self.assertGreater(online.value, 1000)
        self.assertEqual(members.name, "Python")
        with self.assertRaises(cli.CounterError) as caught:
            cli.PROVIDERS["discord.members"].fetch("discord.gg/no-such-invite-xyz987", {})
        self.assertIn("not found", str(caught.exception))

    def test_end_to_end_report(self):
        # The CLI's fetch loop over three sources at once, from an empty
        # cache: every row lands with a value, a name and a tooltip, and a
        # bad target lands as a row error without taking the others down.
        tmp = tempfile.mkdtemp(prefix="omacounter-live-")
        self.addCleanup(shutil.rmtree, tmp)
        saved = cli.STATE_PATH, cli.SECRETS_PATH
        cli.STATE_PATH, cli.SECRETS_PATH = os.path.join(tmp, "state.json"), os.path.join(tmp, "secrets.json")
        self.addCleanup(lambda: setattr(cli, "STATE_PATH", saved[0]) or setattr(cli, "SECRETS_PATH", saved[1]))
        counters = [
            {"type": "github.stars", "target": "octocat/Hello-World"},
            {"type": "mastodon.followers", "target": "Gargron@mastodon.social"},
            {"type": "github.stars", "target": "octocat/no-such-repo-987654"},
        ]
        rows = cli.fetch_all(counters, max_age_minutes=15, force=True)["counters"]
        self.assertEqual([r["error"] for r in rows[:2]], [None, None])
        self.assertTrue(all(r["value"] > 0 and r["name"] and r["tooltip"] for r in rows[:2]))
        self.assertEqual(rows[2]["value"], None)
        self.assertIn("not found", rows[2]["error"])
        # Nothing resolved a name, so the row is labelled by its type.
        self.assertEqual(rows[2]["tooltip"], "GitHub stars\nnot found")
        self.assertTrue(rows[2]["nextFetchAt"])


if __name__ == "__main__":
    unittest.main()
