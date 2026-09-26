"""youtube.views — views of one YouTube video."""

from providers import youtube
from providers.base import CounterError, Provider, Result


class YouTubeViews(Provider):
    id = "youtube.views"
    label = "YouTube views"
    unit = "views"
    icon = "\U000F06D0"  # nf-md-eye
    brand_color = youtube.BRAND_COLOR
    target_help = "video id or video URL"
    target_kind = "video"
    accepts = "a YouTube video (URL or id)"
    describe = "views of one YouTube video"
    example = "dQw4w9WgXcQ"
    credential = youtube.CREDENTIAL
    min_interval = 1
    rate_note = youtube.RATE_NOTE
    group_label = 'YouTube'

    def normalize(self, target):
        return youtube.normalize_video(target)

    def fetch(self, target, secrets):
        item = youtube.first_item(youtube.call("videos", {"part": "snippet,statistics", "id": target}, self.secret(secrets)), "video")
        stats = item.get("statistics") or {}
        if "viewCount" not in stats:
            raise CounterError("no view count in the response")
        return Result(stats["viewCount"], (item.get("snippet") or {}).get("title", ""), self.url(target))

    def url(self, target):
        return youtube.video_url(target)
