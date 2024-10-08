from typing import Literal, Optional
import discord
import json
import os
import datetime
import asqlite
import asyncio
from discord import app_commands
from discord.ext import commands
with open('config.json', 'r') as config_file:
    config = json.load(config_file)

def get_prefix(bot, message):
    prefixes = ['Glyph ','glyph ','Glyph, ','glyph, ']
    if message.channel.type is discord.ChannelType.private:
        return commands.when_mentioned_or(*prefixes)(bot, message)
    return commands.when_mentioned_or(*prefixes)(bot, message)

async def setup_database():
    async with asqlite.connect('glyph_db.db') as conn:
        async with conn.cursor() as cursor:
            print("Cursor obtained!")
            await cursor.executescript('''
                CREATE TABLE IF NOT EXISTS campaigns (
                    campaign_id INTEGER PRIMARY KEY,
                    campaign_name TEXT NOT NULL,
                    gm_id INTEGER NOT NULL,
                    total_sessions INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS players (
                    player_id INTEGER PRIMARY KEY,
                    campaign_id INTEGER NOT NULL,
                    character_name TEXT,
                    FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id)
                );
            ''')
            await conn.commit()
            print("Executed SQL query")
    





intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=get_prefix,description="A little monster who loves taking notes.", intents=intents)


@bot.command()
@commands.guild_only()
@commands.is_owner()
async def sync(ctx: commands.Context, guilds: commands.Greedy[discord.Object], spec: Optional[Literal["~", "*", "^"]] = None) -> None:
    print("Attempting sync!")
    if not guilds:
        print("Not guild")
        if spec == "~":
            synced = await ctx.bot.tree.sync(guild=ctx.guild)
        elif spec == "*":
            ctx.bot.tree.copy_global_to(guild=ctx.guild)
            synced = await ctx.bot.tree.sync(guild=ctx.guild)
        elif spec == "^":
            ctx.bot.tree.clear_commands(guild=ctx.guild)
            await ctx.bot.tree.sync(guild=ctx.guild)
            synced = []
        else:
            synced = await ctx.bot.tree.sync()
        print("End of not guilds")
        print(synced)
        await ctx.send(
            f"Synced {len(synced)} commands {'globally' if spec is None else 'to the current guild.'}"
        )
        return
    print("In between")
    ret = 0
    for guild in guilds:
        print("Guild loop!")
        try:
            await ctx.bot.tree.sync(guild=guild)
        except discord.HTTPException:
            pass
        else:
            ret += 1

    await ctx.send(f"Synced the tree to {ret}/{len(guilds)}.")

@bot.command()
@commands.is_owner()
async def getSessions(ctx):
    response = ''
    if len(bot.sessions.items()) == 0:
        await ctx.send("No sessions!")
        return
    
    for guild_id, session in bot.sessions.items():
        response+=f"Guild ID: {guild_id}, Session: {session}\n"
        for attr in dir(session):
                if not attr.startswith("__"):
                    response += f'{attr}: {getattr(session, attr)}\n'
    print(response)
    await ctx.send(response)

@bot.command()
@commands.is_owner()
async def deleteCampaign(ctx, *, campaign_input: str):
    async with bot.db.acquire() as conn:
        async with conn.cursor() as cursor:
            try:
                await conn.execute('BEGIN')
                
                if campaign_input.isdigit():
                    campaign_id = int(campaign_input)
                else:
                    await cursor.execute(
                        "SELECT campaign_id FROM campaigns WHERE campaign_name = ?",
                        (campaign_input,)
                    )
                    result = await cursor.fetchone()
                    
                    if result is None:
                        await ctx.send(f"Campaign '{campaign_input}' not found. Campaign ID or exact name required")
                        await conn.rollback()
                        return
                    
                    campaign_id = result[0]
                
                await cursor.execute(
                    "DELETE FROM players WHERE campaign_id = ?",
                    (campaign_id,)
                )
                
                await cursor.execute(
                    "DELETE FROM campaigns WHERE campaign_id = ?",
                    (campaign_id,)
                )
                
                await conn.commit()
                await ctx.send(f"Campaign {campaign_id} and associated players deleted successfully.")
            
            except Exception as e:
                await conn.rollback()
                await ctx.send(f"An error occurred: {e}")

@bot.command()
@commands.is_owner()
async def reload(ctx):
    reloads = ''
    for cog in os.listdir(".\\cogs"):
        if cog.endswith(".py"):
            try:
                cog = f"cogs.{cog.replace('.py', '')}"
                await bot.reload_extension(cog)
                reloads +=(cog+'\n')
                print(f'{cog} reloaded!')
            except Exception as e:
                print(f'{cog} cannot be loaded:')
                raise e
    await ctx.send(reloads+'Cogs reloaded')

@bot.command()
async def status(ctx):
    status = ''
    cogs += 'Cogs:\n'+'\n'.join(os.listdir(".\\cogs"))

    await ctx.send(status)

async def load_extensions():
    for filename in os.listdir(".\\cogs"):
        if filename.endswith(".py"):
            await bot.load_extension(f"cogs.{filename[:-3]}")
            print(f'{filename} loaded!')

async def main():
    async with bot:
        bot.db = await asqlite.create_pool('glyph_db.db')
        bot.sessions = {}
        print("Loading Extensions")
        await setup_database()
        await load_extensions()
        await bot.start(config['discord_key'])
        bot.start_time = datetime.datetime.now()
        print("Glyph is awake")

asyncio.run(main())
