"""youtube.subscribers — subscribers of a YouTube channel."""

from providers import youtube
from providers.base import CounterError, Provider, Result


class YouTubeSubscribers(Provider):
    id = "youtube.subscribers"
    label = "YouTube subscribers"
    unit = "subscribers"
    icon = "\U000F05C3"  # nf-md-youtube
    brand_color = youtube.BRAND_COLOR
    target_help = "channel @handle, UC… id, or channel URL"
    target_kind = "channel"
    accepts = "a YouTube channel (URL, @handle or UC… id)"
    describe = "subscribers of a YouTube channel; YouTube rounds it to 3 digits above 1,000"
    example = "@youtube"
    credential = youtube.CREDENTIAL
    min_interval = 1
    rate_note = youtube.RATE_NOTE
    group_label = 'YouTube'

    def normalize(self, target):
        return youtube.normalize_channel(target)

    def fetch(self, target, secrets):
        params = {"part": "snippet,statistics"}
        params["id" if youtube.CHANNEL_ID_RE.match(target) else "forHandle"] = target
        item = youtube.first_item(youtube.call("channels", params, self.secret(secrets)), "channel")
        stats = item.get("statistics") or {}
        if stats.get("hiddenSubscriberCount"):
            raise CounterError("this channel hides its subscriber count")
        if "subscriberCount" not in stats:
            raise CounterError("no subscriber count in the response")
        return Result(stats["subscriberCount"], (item.get("snippet") or {}).get("title", ""), self.url(target))

    def url(self, target):
        return youtube.channel_url(target)
