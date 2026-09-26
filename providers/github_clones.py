"""github.clones — unique cloners of a GitHub repository over the last 14
days, the window GitHub's traffic API reports. Needs a token with access to
the repository (or a logged-in gh CLI)."""

from providers import github
from providers.base import CounterError, Provider, Result


class GitHubClones(Provider):
    id = "github.clones"
    label = "GitHub unique cloners"
    unit = "unique cloners (14 days)"
    icon = "\U000F01DA"  # nf-md-download
    brand_color = github.CLONE_COLOR
    target_help = "owner/repo or github.com URL (a repository you can push to)"
    target_kind = "repository"
    accepts = "a GitHub repository (owner/repo or URL)"
    describe = "people who cloned a GitHub repository in the last 14 days; needs push access"
    example = "octocat/Hello-World"
    credential = github.CREDENTIAL
    default_interval = 60
    min_interval = 15
    rate_note = github.TRAFFIC_RATE_NOTE
    order = 40
    group_label = 'GitHub'

    def normalize(self, target):
        return github.normalize_repo(target)

    def fetch(self, target, secrets):
        token = self.secret(secrets)
        try:
            data = github.get("/repos/%s/traffic/clones" % target, token)
        except CounterError as error:
            if "refused" in str(error) or "no access" in str(error):
                raise CounterError("traffic needs push access to %s — does the token have it?" % target)
            raise
        if not isinstance(data, dict) or "uniques" not in data:
            raise CounterError("no clone count in the response")
        return Result(data["uniques"], target, self.url(target))

    def url(self, target):
        return github.repo_url(target) + "/graphs/traffic"
