"""discord.members — members of a Discord server, from its invite link."""

from providers import discord
from providers.base import CounterError, Provider, Result


class DiscordMembers(Provider):
    id = "discord.members"
    label = "Discord members"
    unit = "members"
    icon = "\U000F066F"  # nf-md-discord
    brand_color = discord.BRAND_COLOR
    target_help = "invite link (discord.gg/<code>)"
    target_kind = "Discord server"
    accepts = "a Discord invite link (discord.gg/…)"
    describe = "members of a Discord server, from a permanent invite link"
    example = "discord.gg/python"
    credential = None
    min_interval = 5
    rate_note = discord.RATE_NOTE
    group_label = "Discord"

    def normalize(self, target):
        return discord.normalize_invite(target)

    def fetch(self, target, secrets):
        data = discord.lookup(target)
        count = data.get("approximate_member_count")
        if not isinstance(count, int):
            raise CounterError("no member count in the response (the invite may lead to a group, not a server)")
        return Result(count, discord.server_name(data, target), self.url(target))

    def url(self, target):
        return discord.invite_url(target)
