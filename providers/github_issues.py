"""github.issues — open issues of a GitHub repository (pull requests not
counted). Public search API, no token needed."""

from providers import github
from providers.base import Provider, Result


class GitHubIssues(Provider):
    id = "github.issues"
    label = "GitHub open issues"
    unit = "open issues"
    icon = "\U000F0028"  # nf-md-alert_circle
    brand_color = github.OPEN_COLOR
    target_help = "owner/repo or github.com URL"
    target_kind = "repository"
    accepts = "a GitHub repository (owner/repo or URL)"
    describe = "open issues of a GitHub repository, pull requests not counted"
    example = "octocat/Hello-World"
    credential = None
    min_interval = 5
    rate_note = github.SEARCH_RATE_NOTE
    order = 20
    group_label = 'GitHub'

    def normalize(self, target):
        return github.normalize_repo(target)

    def fetch(self, target, secrets):
        count = github.search_count(target, "is:issue is:open", secrets)
        return Result(count, target, self.url(target))

    def url(self, target):
        return github.repo_url(target) + "/issues"
