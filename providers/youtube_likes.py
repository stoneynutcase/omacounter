"""youtube.likes — likes on one YouTube video."""

from providers import youtube
from providers.base import CounterError, Provider, Result


class YouTubeLikes(Provider):
    id = "youtube.likes"
    label = "YouTube likes"
    unit = "likes"
    icon = "\U000F0513"  # nf-md-thumb_up
    brand_color = youtube.BRAND_COLOR
    target_help = "video id or video URL"
    target_kind = "video"
    accepts = "a YouTube video (URL or id)"
    describe = "likes on one YouTube video"
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
        if "likeCount" not in stats:
            raise CounterError("likes are hidden for this video")
        return Result(stats["likeCount"], (item.get("snippet") or {}).get("title", ""), self.url(target))

    def url(self, target):
        return youtube.video_url(target)
