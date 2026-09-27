# Developing Omacounter

Notes for working on the plugin. If you just want to use it, the
[README](README.md) is the whole story.

## How it works

```
bin/omacounter      the CLI: config, state, the fetch loop, the wizard, the commands
providers/               one file per counter type, plus shared modules
  base.py                the Provider and Credential contracts, Result, errors, http_json
  __init__.py            discovery: every *.py here is imported and its providers registered
  youtube.py             shared YouTube code: the API key credential, the client, the parsers
  mastodon.py            shared Mastodon code: account and tag parsers, the public lookups
  github.py              shared GitHub code: the token credential (with gh CLI fallback), requests, repo parser
  youtube_subscribers.py youtube_likes.py  youtube_views.py
  github_stars.py        github_issues.py  github_pulls.py  github_clones.py
  mastodon_followers.py  mastodon_posts.py  mastodon_tag.py  mastodon_tagpeople.py
  discord.py             shared Discord code: invite link parser, the public invite lookup
  discord_members.py     discord_online.py
Panel.qml                the popup and the fetch process; derives what the bar face shows
BarWidget.qml            the bar entry point: paints the entries the panel hands it
FlipDigit.qml            one split-flap card
Model.js                 pure formatting helpers shared by the QML (node runs them in the tests)
```

The pieces do not overlap:

- **`bin/omacounter`** owns everything that is not a source. Its `fetch`
  command takes the counter list, asks the providers for whatever is due,
  folds in the cache, and prints one JSON report. The same file is the
  `setup` wizard and the `add`/`set`/`remove`/`list`/`auth` CLI. It knows
  nothing about YouTube or GitHub.
- **`providers/`** is where every source lives. The CLI reads the registry
  and drives `setup`, `add`, `types`, `doctor` and `fetch` from the
  attributes each provider declares. Only these files talk to the network.
- **`Panel.qml`** runs `fetch` on a timer (and on demand), parses the
  report, and renders the popup. It also derives what the bar face shows.
- **`BarWidget.qml`** loads the panel once and paints the entries the panel
  hands it.

`FlipDigit.qml` is one split-flap card built like the real thing: two fixed
half faces and one leaf hinged on the centre line that falls through 180
degrees with an x-axis `Rotation`. The leaf's front carries the top half of
the old digit; its back, pre-mirrored with a `Scale` so it reads upright
after the turn, carries the bottom half of the new digit and takes over past
edge-on. A card steps one leaf at a time toward its target, forward only and
wrapping past 9, quick on the way and slower on the landing leaf. The panel
keys its rows and cards by position (number models, not the report array) so
a fetch that changes a value flips only the digits that changed instead of
rebuilding the row.

### Helpers, environment and the network

Rules that hold across the CLI and the panel, and that the marketplace's
review checks against the README's "What it touches" section:

- A helper (`gh`, `gum`, `xdg-open`, Omarchy's commands) is run only by the
  absolute path `providers/base.py` `trusted_tool` returns: a root-owned,
  not-otherwise-writable file in `/usr/local/bin`, `/usr/bin`, `/bin` or
  Omarchy's bin directory, reached through root-owned symlinks only. Never
  `shutil.which`, never a bare name.
- The panel starts the CLI as `/usr/bin/python3 <cli>` with
  `clearEnvironment: true` and the allowlist in `buildChildEnv`; the CLI's
  shebang is `/usr/bin/python3`. Automatic subprocesses (`gh auth token`)
  get `minimal_env()`.
- All fetching goes through `http_json`: https only, https-only redirects
  capped at `MAX_REDIRECTS`, `MAX_RESPONSE_BYTES`, `HTTP_TIMEOUT`. A
  provider never opens a socket itself.
- A credential is never an argument: `auth … set` prompts or reads stdin,
  and `fetch_all` scrubs every held credential from error text.
- Files are written with `write_json` (random temp name, rename into place);
  the secrets and the cache are read with `nofollow`.

### When fetches happen

Two timers in `Panel.qml`, both cheap because the CLI serves anything not
due from its cache. A periodic one ticks at the smallest interval any
counter asks for (the report's `effectiveInterval`, which a source's rate
cap may have raised). A one-shot one is re-armed on every report to the
earliest `nextFetchAt` any row carries: a failed counter's retry (two
minutes after the attempt, or the source's cap if longer), a rate-limited
counter's next slot, or a plain counter's interval. So "retry 18:48" in a
row is when the retry actually runs, not the next tick after it. The
one-shot never fires sooner than a minute after arming, the CLI's own floor.

### Where the counters live

On the widget's own entry in `~/.config/omarchy/shell.json`, following
Omarchy's rule that a plugin's settings are inline on its entry: no separate
config file, one place to hand-edit, hot-reloaded on save, and reachable from
the panel through `bar.shell.updateEntryInline` (that is how a row's `󰅖`
removes a counter, `󰛐` hides it from the bar, and dragging `󰍜` moves it).

The list has one order, computed the same way in `Model.js` (`groupRows`,
`moveOrder`, `moveGroupOrder`) and the CLI (`group_rows`, `move_counter`,
`move_group`): groups in order of first appearance, each group's counters in
configured order. The bar, the tooltip, the notification and the panel all
show it, and a CLI write stores it, so an interleaved hand-written list is
tidied the first time anything is saved. A drag in the panel only shows a
ghost and a drop line while the pointer moves; on release the move is
applied to the report the panel already has (rows change place at once,
cards snap rather than flip) and to the configured list, which is saved;
the refetch the save triggers then returns rows in that same order. A
report that lands mid-drag is dropped, since it may be in another order.

The CLI writes the file directly (atomically, through a temp file and
rename), not through `omarchy bar set … --json`: the shell's IPC layer splits
a bracketed argument on its commas, so an array never arrives intact. Scalar
settings such as `refreshMinutes` are fine through `omarchy bar set`.

Settings are read from `shell.json` directly (a watched `FileView` in
`Panel.qml`), with the injected `settings` only as a fallback. The bar
applies a changed entry to a running widget by patching its layout in place
and pushing the new settings to the mounted item, but the layout entries the
Repeater holds are not updated, so the next plugin reload re-mounts the
widget with the pre-patch entry: a counter removed since the shell started
comes back. Reading the file, which the shell writes on every change,
sidesteps that. (Worth reporting upstream; it affects any inline setting on
any widget.)

Keys and tokens go to `~/.config/omacounter/secrets.json` at mode 600,
keyed by credential id (`{"youtube": {"apiKey": "…"}, "github": {"token": "…"}}`),
because `shell.json` tends to end up in a dotfiles repo. A credential can
widen where it looks: `GitHubToken.from_env` falls back to `gh auth token`,
so a machine with a logged-in `gh` needs nothing stored, and the public
GitHub types send that token too when it is there (`github.optional_token`),
which lifts their rate limit. The cache and the daily history live in
`~/.local/state/omacounter/state.json`; the CLI prunes entries for
counters that are no longer configured.

A bar exists per monitor, so there is one widget and one panel per monitor
too, but an IPC target routes to a single handler. Anything that arrives
from outside — `omacounter refresh` after add/remove/set, a keybind —
goes through `BarWidget.refreshAll()`, which is `broadcast("refresh")` over
`bar.moduleWidgets(id)`; a plain `refresh()` is one instance only.

One more trap, already handled in `configuredCounters`: an array on the
shell.json entry reaches the widget as a Qt list wrapper when the bar mounts
it, so `Array.isArray` says no while `JSON.stringify` prints it fine.
Normalise through `Util.cloneJson` before reading, as the first-party
Indicators widget does with its `items`.

### The fetch contract

```
bin/omacounter fetch --counters '<json array>' --max-age 15 [--force]
```

prints

```json
{
  "generatedAt": "2026-09-22T12:04:05",
  "configured": true,
  "counters": [
    { "index": 0, "type": "github.stars", "target": "octocat/Hello-World",
      "label": "octocat/Hello-World", "icon": "󰓎", "unit": "stars",
      "group": "github", "groupLabel": "GitHub",
      "brandColor": "#E3B341", "brandTextColor": "", "credential": "",
      "color": "", "glyphColor": "", "textColor": "", "style": "",
      "interval": null, "defaultInterval": null, "minInterval": 5, "effectiveInterval": 15,
      "rateLimited": false, "nextFetchAt": "2026-09-22T12:19:05",
      "value": 3825, "name": "octocat/Hello-World", "url": "https://github.com/octocat/Hello-World",
      "fetchedAt": "2026-09-22T12:04:05", "error": null,
      "deltaDay": 12, "deltaWeek": 80,
      "tooltip": "octocat/Hello-World\n3,825 stars  ·  +12 today" }
  ]
}
```

A counter is fetched when it has never been, when its effective interval has
elapsed, or under `--force` — except that a provider's `min_interval` (its
rate cap) always holds: a forced fetch inside the cap serves the cached
value and sets `rateLimited`, and the panel says how long ago it was fetched. The
effective interval is the counter's `interval`, else the provider's
`default_interval`, else `--max-age`, raised to `min_interval`. A failed
fetch keeps the last good `value`, sets `error`, and is retried after two
minutes or the cap, whichever is longer. The report always exits 0; per-counter
problems are inside it, so the panel can show them on the right row. Only a
broken invocation exits non-zero.

## Adding a source

A source is one file, `providers/<service>_<metric>.py`, defining one subclass
of `Provider` whose `id` is `<service>.<metric>`. Nothing else changes:
discovery imports every file in the directory, and `setup`, `add`, `list`,
`types`, `doctor`, the panel and the bar read the registry. Both contracts
are documented in full in [`providers/base.py`](providers/base.py); this is
the shape:

```python
class Provider:
    id = ""                 # the `type` on a counter: "<service>.<metric>"
    label = ""              # default label until the first fetch resolves a name
    unit = ""               # "stars"
    icon = ""               # one Nerd Font glyph
    brand_color = ""        # default glyph colour "#RRGGBB", or "" to follow the bar
    text_color = ""         # default number colour, same values
    target_help = ""        # "owner/repo or github.com URL"
    target_kind = ""        # "repository": the wizard says "That is a repository — count what?"
    accepts = ""            # wizard prompt phrase: "a GitHub repository (owner/repo or URL)"
    describe = ""           # one line for `types`
    example = ""            # a valid canonical target; the tests check normalize(example) == example
    credential = None       # a Credential instance shared with siblings, or None
    default_interval = None # minutes; None = the widget's refreshMinutes
    min_interval = 1        # minutes; the fastest this source may be polled (enforced)
    rate_note = ""          # why: "60 requests an hour per IP without a token"
    order = 100             # sort key: what `types` lists first and what the wizard preselects
    group = ""              # section in the panel; defaults to the id's prefix ("youtube")
    group_label = ""        # that section's title; defaults to the group capitalised ("YouTube")

    def normalize(self, target) -> str        # canonical target; ValueError with an actionable sentence
    def fetch(self, target, secrets) -> Result # CounterError with a one-line row error
    def url(self, target) -> str              # "" when nothing to open
    def tooltip(self, row) -> str             # bar tooltip; default_tooltip(row) unless overridden
```

`github_stars.py` is the worked example of a source that needs no credential:

```python
class GitHubStars(Provider):
    id = "github.stars"
    label = "GitHub stars"
    unit = "stars"
    icon = "\U000F04CE"
    brand_color = "#E3B341"
    target_help = "owner/repo or github.com URL"
    target_kind = "repository"
    accepts = "a GitHub repository (owner/repo or URL)"
    describe = "stargazers of a GitHub repository"
    example = "octocat/Hello-World"
    min_interval = 5
    rate_note = "60 requests an hour per IP without a token"

    def normalize(self, target): ...          # owner/repo, github.com URLs, git@github.com:… → "owner/repo"
    def fetch(self, target, secrets):
        data = http_json("https://api.github.com/repos/" + target, headers=HEADERS)
        return Result(data["stargazers_count"], data.get("full_name"), data.get("html_url"))
    def url(self, target): return "https://github.com/" + target
```

### Adding a credential

A source that needs a key or token declares a `Credential` once, in a module
its siblings share, and points `credential` at that instance. `auth <id>`,
the wizard step, `doctor` and the "no key" row error are generic over it:

```python
# providers/bluesky.py (shared)
class BlueskyToken(Credential):
    id = "bluesky"
    kind = "token"                       # stored as {"bluesky": {"token": "…"}}
    label = "Bluesky app password"
    help = "Settings → App passwords on bsky.app; only reads your profile."
    console_url = "https://bsky.app/settings/app-passwords"
    env = "BLUESKY_APP_PASSWORD"
    placeholder = "xxxx-xxxx-xxxx-xxxx"
    shape = re.compile(r"^[a-z0-9]{4}(-[a-z0-9]{4}){3}$")
    shape_help = "four groups of four, separated by dashes"

    def verify(self, value): ...         # one cheap call; raise CounterError on failure

CREDENTIAL = BlueskyToken()

# providers/bluesky_followers.py
class BlueskyFollowers(Provider):
    id = "bluesky.followers"
    credential = bluesky.CREDENTIAL
    def fetch(self, target, secrets):
        token = self.secret(secrets)     # resolves file → env, or raises the "run: auth bluesky set" error
        ...
```

Rules the base class expects:

- `normalize()` raises `ValueError` with a sentence a person can act on; the
  wizard prints it and asks again. When the input clearly belongs to a
  sibling type, say so (see `youtube.normalize_channel`).
- `fetch()` raises `CounterError` with one line for the panel row. Anything
  else it raises is caught and shown with the exception's name, so a bug in
  one provider never blanks the others.
- `fetch()` must be safe to run in a thread; the CLI fetches due counters
  four at a time.
- Use `http_json()` for requests: it sets the user agent, bounds the response
  size, and maps HTTP errors (`HttpError.message` carries the service's own
  message, Google's or GitHub's shape). A key in the query string is fine;
  requests are made in-process, so it never appears on a command line.
- Set `min_interval` from the service's real limits and say why in
  `rate_note`; the fetch loop enforces it and `set … interval` refuses
  values below it.
- Two types that accept the same link (likes and views for a video,
  followers and posts for a Mastodon account, four things for a repository)
  are what the wizard's "count what?" question is for; make their
  `target_kind` and `accepts` identical, and give the keyless favourite the
  lowest `order` so it is the one preselected.
- A new address format must not claim another service's: the tests check
  that a YouTube handle, a video URL, a repository and a Mastodon account
  each detect only their own types. Reject the other services' hosts
  explicitly where a pattern is generic (see `mastodon.NOT_MASTODON_HOSTS`).

Then run `omacounter types` to see the new line, and the tests: the
contract test checks every declared field, `normalize(example)`, `url()`, the
tooltip, and the file-name convention.

## Reloading

The shell watches `~/.config/omarchy/plugins/` and reloads plugin code on
save, with the same caveats other plugins have:

| Changed | Takes effect |
| --- | --- |
| `BarWidget.qml` | on save (the bar remounts the widget) |
| **`Panel.qml`, `FlipDigit.qml`** | **only after `omarchy restart shell`** — loaded through a `Loader`, and the QML engine keeps the compiled components cached across plugin reloads |
| **`Model.js`** | **only after `omarchy restart shell`** — the compiled JS stays cached the same way |
| `bin/omacounter`, `providers/*.py` | next fetch; scripts are re-read per invocation |
| `manifest.json` | `omarchy-shell shell rescanPlugins` |
| the entry in `shell.json` | on save |

The Panel.qml case bites: the reload log says the plugin reloaded, the bar
remounts the widget, and the old panel keeps running. If a change to the
panel or to a fetch path seems to be ignored, restart the shell before
debugging anything else. `console.log` from plugin QML shows up in the
journal as `DEBUG qml:` lines.

## Testing a local checkout

The plugin is installed as its own clone under
`~/.config/omarchy/plugins/stoneynutcase.omacounter`, so editing your
checkout changes nothing about the running plugin. `omarchy plugin add`
takes a local path (it clones whatever `HEAD` points at, so commit first):

```bash
omarchy plugin remove stoneynutcase.omacounter --yes
omarchy plugin add /path/to/your/checkout --enable --yes
```

For a quick round trip without committing, copy the tree over instead — the
registry does not follow a symlinked plugin directory:

```bash
rsync -a --delete --exclude .git --exclude __pycache__ ./ ~/.config/omarchy/plugins/stoneynutcase.omacounter/
omarchy restart shell   # needed for Panel.qml and Model.js, see above
```

Shell log: `journalctl --user -o cat _COMM=quickshell`.

## Tests

```bash
python3 -m unittest discover -s test -v     # the CLI and providers, offline
node --test "test/*.test.mjs"                            # Model.js

# Live, against the real services (what .github/workflows/integration.yml runs
# daily and on every change to providers/, bin/ or test/):
OMACOUNTER_LIVE=1 python3 -m unittest discover -s test -p test_cli.py -k LiveKeyless -v
YOUTUBE_API_KEY=… python3 -m unittest discover -s test -p test_cli.py -k LiveYouTube -v
```

The keyed job takes the key from the repository secret `YOUTUBE_API_KEY`;
a pull request from a fork gets no secret and the YouTube tests skip rather
than fail. The keyless job runs with the workflow's own `GITHUB_TOKEN` so
GitHub's unauthenticated limit does not bite on a shared runner address. A
failing scheduled run opens (or comments on) an issue titled "Daily
integration run is failing".

Nothing to install. The Python tests load `bin/omacounter` as a module,
which puts the plugin root on `sys.path` so `providers` is the same package
the CLI registered; they point its config, state and secrets paths at a
temporary directory and replace the providers' `fetch` with fakes, so they
cover URL parsing, discovery and the contract, credential resolution, the
due/cached/error logic and the rate cap, the history deltas and the report
shape without a network or a key.

Set `YOUTUBE_API_KEY` to also run the live YouTube tests, and
`OMACOUNTER_LIVE=1` for the live GitHub one; without them they skip.
