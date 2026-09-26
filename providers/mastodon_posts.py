"""mastodon.posts — posts by a Mastodon account, on any instance."""

from providers import mastodon
from providers.base import CounterError, Provider, Result


class MastodonPosts(Provider):
    id = "mastodon.posts"
    label = "Mastodon posts"
    unit = "posts"
    icon = "\U000F0AD1"  # nf-md-mastodon
    brand_color = mastodon.BRAND_COLOR
    target_help = "user@instance or profile URL"
    target_kind = "Mastodon account"
    accepts = "a Mastodon account (user@instance or profile URL)"
    describe = "posts by a Mastodon account, on any instance"
    example = "Gargron@mastodon.social"
    credential = None
    min_interval = 5
    rate_note = mastodon.RATE_NOTE
    group_label = 'Mastodon'

    def normalize(self, target):
        return mastodon.normalize_account(target)

    def fetch(self, target, secrets):
        data = mastodon.lookup(target)
        if "statuses_count" not in data:
            raise CounterError("no post count in the response")
        return Result(data["statuses_count"], mastodon.display_name(data, target), data.get("url") or self.url(target))

    def url(self, target):
        return mastodon.profile_url(target)
