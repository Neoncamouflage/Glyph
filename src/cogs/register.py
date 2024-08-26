import discord
from discord import app_commands
from discord.ext import commands

class Register(commands.GroupCog, name="register"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="campaign", description="Glyph will register a new campaign with you as the DM.")
    async def campaign(self, interaction: discord.Interaction, campaign_name: str) -> None:
        print("Registering new campaign!")

        campaign_name = campaign_name.strip()
        if not campaign_name:
            await interaction.response.send_message("Campaign name cannot be empty.", ephemeral=True)
            return

        async with self.bot.db.acquire() as conn:
            async with conn.cursor() as cursor:
                try:
                    await cursor.execute(
                        "INSERT INTO campaigns (campaign_name, gm_id) VALUES (?, ?)",
                        (campaign_name, interaction.user.id)
                    )
                    await conn.commit()
                    await interaction.response.send_message(f"Campaign '{campaign_name}' registered successfully!")
                except Exception as e:
                    await conn.rollback()
                    await interaction.response.send_message(f"Failed to register campaign: {str(e)}")

    @app_commands.command(name="character", description="Tells Glyph to register a new character for a campaign and assign it to you.")
    async def character(self, interaction: discord.Interaction, campaign_name: str, character_name: str) -> None:

        character_name = character_name.strip()
        if not character_name:
            await interaction.response.send_message("Character name cannot be empty.", ephemeral=True)
            return

        async with self.bot.db.acquire() as conn:
            async with conn.cursor() as cursor:
                try:
                    await cursor.execute("SELECT campaign_id FROM campaigns WHERE campaign_name = ?", (campaign_name,))
                    campaign_id = await cursor.fetchone()
                    if not campaign_id:
                        await interaction.response.send_message(f"Campaign '{campaign_name}' not found.")
                        return
                    
                    campaign_id = campaign_id[0]

                    await cursor.execute(
                        "INSERT INTO players (campaign_id, character_name) VALUES (?, ?)",
                        (campaign_id, character_name)
                    )
                    await conn.commit()
                    await interaction.response.send_message(f"Character '{character_name}' registered successfully under campaign '{campaign_name}'!")
                except Exception as e:
                    await conn.rollback()
                    await interaction.response.send_message(f"Failed to register character: {str(e)}")

    @character.autocomplete('campaign_name')
    async def autocomplete_campaign_name(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice]:
        async with self.bot.db.acquire() as conn:
            async with conn.cursor() as cursor:
                try:
                    await cursor.execute("SELECT campaign_name FROM campaigns")
                    campaigns = await cursor.fetchall()


                    return [
                        app_commands.Choice(name=campaign[0], value=campaign[0])
                        for campaign in campaigns if current.lower() in campaign[0].lower()
                    ][:25]
                except Exception as e:
                    await interaction.response.send_message(f"Failed to register character: {str(e)}")

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Register(bot))
