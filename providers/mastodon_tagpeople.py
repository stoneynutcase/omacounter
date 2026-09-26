"""mastodon.tagpeople — accounts that used a hashtag on one instance over the
last seven days (the window the public tag endpoint reports)."""

from providers import mastodon
from providers.base import Provider, Result


class MastodonTagPeople(Provider):
    id = "mastodon.tagpeople"
    label = "Mastodon tag people"
    unit = "people this week"
    icon = "\U000F0423"  # nf-md-pound
    brand_color = mastodon.BRAND_COLOR
    target_help = "#tag@instance or tag URL"
    target_kind = "Mastodon tag"
    accepts = "a Mastodon tag (#tag@instance or https://instance/tags/tag)"
    describe = "accounts that used a hashtag on one instance, last seven days"
    example = "#TuneTuesday@mastodon.social"
    credential = None
    min_interval = 5
    rate_note = mastodon.RATE_NOTE
    group_label = 'Mastodon'

    def normalize(self, target):
        return mastodon.normalize_tag(target)

    def fetch(self, target, secrets):
        data = mastodon.tag_lookup(target)
        return Result(mastodon.history_sum(data, "accounts"), mastodon.tag_name(data, target), data.get("url") or self.url(target))

    def url(self, target):
        return mastodon.tag_url(target)
