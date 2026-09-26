"""github.pulls — open pull requests of a GitHub repository. Public search
API, no token needed."""

from providers import github
from providers.base import Provider, Result


class GitHubPulls(Provider):
    id = "github.pulls"
    label = "GitHub open pull requests"
    unit = "open pull requests"
    icon = "\U000F04C2"  # nf-md-source_pull
    brand_color = github.PULL_COLOR
    target_help = "owner/repo or github.com URL"
    target_kind = "repository"
    accepts = "a GitHub repository (owner/repo or URL)"
    describe = "open pull requests of a GitHub repository"
    example = "octocat/Hello-World"
    credential = None
    min_interval = 5
    rate_note = github.SEARCH_RATE_NOTE
    order = 30
    group_label = 'GitHub'

    def normalize(self, target):
        return github.normalize_repo(target)

    def fetch(self, target, secrets):
        count = github.search_count(target, "is:pr is:open", secrets)
        return Result(count, target, self.url(target))

    def url(self, target):
        return github.repo_url(target) + "/pulls"
