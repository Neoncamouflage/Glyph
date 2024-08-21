import os
import json
import discord
from discord.ext import commands, voice_recv, tasks
from discord import app_commands


class Notes(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Notes(bot))