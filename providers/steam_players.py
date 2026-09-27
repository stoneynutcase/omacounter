"""steam.players — players in a Steam game right now."""

from providers import steam
from providers.base import Provider, Result


class SteamPlayers(Provider):
    id = "steam.players"
    label = "Steam players"
    unit = "playing now"
    icon = "\uF1B6"  # nf-fa-steam (U+F04A3, the "md" guess, is the silverware)
    brand_color = steam.BRAND_COLOR
    target_help = "store URL or app id"
    target_kind = "Steam game"
    accepts = "a Steam game (store URL or app id)"
    describe = "players in a Steam game right now (goes down as well as up)"
    example = "730"
    credential = None
    min_interval = 5
    rate_note = steam.RATE_NOTE
    group_label = "Steam"

    def normalize(self, target):
        return steam.normalize_app(target)

    def fetch(self, target, secrets):
        count = steam.player_count(target)
        return Result(count, steam.app_name(target) or ("Steam app " + target), self.url(target))

    def url(self, target):
        return steam.store_url(target)
