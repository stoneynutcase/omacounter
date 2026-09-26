"""github.stars — stargazers of a GitHub repository. Public API, no token."""

from providers import github
from providers.base import CounterError, Provider, Result


class GitHubStars(Provider):
    id = "github.stars"
    label = "GitHub stars"
    unit = "stars"
    icon = "\U000F04CE"  # nf-md-star
    brand_color = github.STAR_COLOR
    target_help = "owner/repo or github.com URL"
    target_kind = "repository"
    accepts = "a GitHub repository (owner/repo or URL)"
    describe = "stargazers of a GitHub repository"
    example = "octocat/Hello-World"
    credential = None
    min_interval = 5
    rate_note = github.RATE_NOTE
    order = 10
    group_label = 'GitHub'

    def normalize(self, target):
        return github.normalize_repo(target)

    def fetch(self, target, secrets):
        data = github.repo_json(target, secrets)
        if "stargazers_count" not in data:
            raise CounterError("no star count in the response")
        return Result(data["stargazers_count"], data.get("full_name") or target, data.get("html_url") or self.url(target))

    def url(self, target):
        return github.repo_url(target)
