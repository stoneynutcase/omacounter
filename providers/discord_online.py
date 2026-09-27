"""discord.online — members of a Discord server online right now."""

from providers import discord
from providers.base import CounterError, Provider, Result


class DiscordOnline(Provider):
    id = "discord.online"
    label = "Discord online"
    unit = "online now"
    icon = "\U000F0430"  # nf-md-pulse: a live signal, apart from the members' Discord mark
    brand_color = discord.BRAND_COLOR
    target_help = "invite link (discord.gg/<code>)"
    target_kind = "Discord server"
    accepts = "a Discord invite link (discord.gg/…)"
    describe = "members of a Discord server online right now (goes down as well as up)"
    example = "discord.gg/python"
    credential = None
    min_interval = 5
    rate_note = discord.RATE_NOTE
    group_label = "Discord"

    def normalize(self, target):
        return discord.normalize_invite(target)

    def fetch(self, target, secrets):
        data = discord.lookup(target)
        count = data.get("approximate_presence_count")
        if not isinstance(count, int):
            raise CounterError("no online count in the response")
        return Result(count, discord.server_name(data, target), self.url(target))

    def url(self, target):
        return discord.invite_url(target)
