import discord
import os
import time
import json
from discord.ext import commands, voice_recv, tasks
from discord import app_commands
import aiofiles
import apiClient

MAX_FILE_SIZE_MB = 1
MAX_MESSAGE_LENGTH = 2000

class CampaignSelectButton(discord.ui.Button):
    def __init__(self, campaign_id: int, campaign_name: str, view):
        try:
            super().__init__(label=campaign_name, style=discord.ButtonStyle.primary)
            self.campaign_id = campaign_id
        except Exception as e:
            print(f"Exception occurred: {e}")

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_campaign = {'campaign_id': self.campaign_id, 'campaign_name': self.label}
        await interaction.response.edit_message(content=f"Today's campaign is {self.label}!", view=None)
        self.view.stop()

class CampaignSelectView(discord.ui.View):
    def __init__(self, campaigns):
        super().__init__()
        self.selected_campaign = None

        for campaign_id, campaign_name, total_sessions in campaigns:
            self.add_item(CampaignSelectButton(campaign_id, campaign_name, self))

class RecordingSession:
    def __init__(self, guild_id, voice_client, campaign):
        self.guild_id = guild_id
        self.voice_client = voice_client
        self.user_sinks = {}
        self.user_fileStart = {}
        self.recording = False
        self.campaign_name = campaign['campaign_name']
        self.campaign_id = campaign['campaign_id']
        self.session_number = campaign['total_sessions']+1
        self.session_start = None

    def start_recording(self):
        self.recording = True
        if not self.session_start:
            self.session_start = round(time.time())

    def stop_recording(self):
        self.recording = False
        for sink in self.user_sinks.values():
            sink.cleanup()
        self.user_sinks.clear()

    def add_user_sink(self, user, sink):
        self.user_sinks[user] = sink
        sink.fileStart = round(time.time())

    def is_recording(self):
        return self.recording

class Recorder(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.file_size_monitor.start()
    
    @tasks.loop(seconds=60)
    async def file_size_monitor(self):
        for session in self.bot.sessions.values():
            if session.is_recording():
                for user, sink in session.user_sinks.items():
                    filename = sink.filename
                    if os.path.exists(filename):
                        file_size_mb = os.path.getsize(filename) / (1024 * 1024)
                        print(f'File size for {filename} currently {file_size_mb}')
                        if file_size_mb >= MAX_FILE_SIZE_MB:
                            await self.handle_file_size_limit_reached(session, user)

    async def handle_file_size_limit_reached(self, session, user):
        current_file = session.user_sinks[user].filename
        file_start = session.user_sinks[user].fileStart
        base_name, ext = os.path.splitext(current_file)

        parts = base_name.split('_')

        index = int(parts[-1])

        parts[-1] = str(index + 1)
        new_base_name = '_'.join(parts)
        new_filename = f"{new_base_name}{ext}"

        session.user_sinks[user].cleanup()
        session.add_user_sink(user, voice_recv.FFmpegSink(filename=new_filename))
        print(f"Switched to new file: {new_filename}")
        await apiClient.transcribe_file(current_file,user.id,session,file_start)

    async def select_campaign(self, interaction: discord.Interaction, campaigns) -> dict:
        if len(campaigns) == 1:
            return {'campaign_id': campaigns[0][0], 'campaign_name': campaigns[0][1], 'total_sessions': campaigns[0][2]}

        view = CampaignSelectView(campaigns)
        await interaction.response.send_message("Is it time to play? Oh boy! Which campaign is this session for?", view=view)
        await view.wait()

        if view.selected_campaign:
            # Fetch total_sessions from the selected campaign
            for campaign_id, campaign_name, total_sessions in campaigns:
                if campaign_id == view.selected_campaign['campaign_id']:
                    view.selected_campaign['total_sessions'] = total_sessions
                    break
            return view.selected_campaign
        else:
            await interaction.followup.send("You didn't select a campaign in time!")
            return None

    @app_commands.command(name="join", description="Tells Glyph to join a voice channel and prepare for the session.")
    async def join(self, interaction: discord.Interaction) -> None:
        async with self.bot.db.acquire() as conn:
            async with conn.cursor() as cursor:
                try:
                    print(f"Requesting campaigns for user {interaction.user.name}")
                    await cursor.execute('''
                        SELECT campaign_id, campaign_name, total_sessions
                        FROM campaigns
                        WHERE gm_id = ?

                        UNION

                        SELECT c.campaign_id, c.campaign_name, c.total_sessions
                        FROM campaigns c
                        JOIN players p ON c.campaign_id = p.campaign_id
                        WHERE p.player_id = ?;
                    ''', (interaction.user.id, interaction.user.id))

                    # Fetch all results
                    campaigns = await cursor.fetchall()
                    print("Campaigns found", campaigns)
                except Exception as e:
                    await interaction.response.send_message(f"Database query failed! Oh no! This happened:\n{str(e)}")
                    return

        if not campaigns:
            await interaction.response.send_message(f"You aren't in any campaigns! Register or join one so I know what we're playing.")
            return

        campaignPick = await self.select_campaign(interaction, campaigns)
        if not campaignPick:
            return

        if interaction.user.voice:
            try:
                voice_client = await interaction.user.voice.channel.connect(cls=voice_recv.VoiceRecvClient)
                session = RecordingSession(interaction.guild.id, voice_client, campaignPick)
                self.bot.sessions[interaction.guild.id] = session
                if interaction.response.is_done():
                    await interaction.followup.send(f"Joined the voice channel! Campaign: {campaignPick['campaign_name']}, Session {campaignPick['total_sessions']+1}")
                else:
                    await interaction.response.send_message(f"Joined the voice channel! Campaign: {campaignPick['campaign_name']}, Session {campaignPick['total_sessions']+1}")
            except Exception as e:
                print(f"Exception occurred during voice connection or session creation: {e}")
                if interaction.response.is_done():
                    await interaction.followup.send(f"Failed to join the voice channel: {str(e)}")
                else:
                    await interaction.response.send_message(f"Failed to join the voice channel: {str(e)}")
                return
        else:
            if interaction.response.is_done():
                await interaction.followup.send("You need to be in a voice channel for me to join.")
            else:
                await interaction.response.send_message("You need to be in a voice channel for me to join.")
        print("Join command finished")



    @app_commands.command(name="listen", description="Tells Glyph to start listening to your session.")
    async def listen(self, interaction: discord.Interaction) -> None:
        session = self.bot.sessions.get(interaction.guild_id)
        if session and not session.is_recording():
            def callback(user, data: voice_recv.VoiceData):
                if user not in session.user_sinks:
                    print("Found new user")
                    base_filename = f"{session.campaign_id}_{session.session_number}_{user.name}_"
                    index = 1
                    filename = f"{base_filename}{index}.mp3"

                    while os.path.exists(filename):
                        index += 1
                        filename = f"{base_filename}{index}.mp3"

                    session.add_user_sink(user, voice_recv.FFmpegSink(filename=filename))

                session.user_sinks[user].write(user, data)

            session.voice_client.listen(voice_recv.BasicSink(callback))
            session.start_recording()
            await interaction.response.send_message("I'm ready!")
        elif not session:
            await interaction.response.send_message("What? I'm not prepared yet! Tell me which channel to join.")
        else:
            await interaction.response.send_message("I'm already listening!")
        print("Listen command finished")

    @app_commands.command(name="stop", description="Tells Glyph to stop listening.")
    async def stop(self, interaction: discord.Interaction) -> None:
        session = self.bot.sessions.get(interaction.guild_id)
        if session and session.is_recording():
            await interaction.response.send_message("Ok! Taking a break for now")
            print("Recording in stop command")
            session.voice_client.stop_listening()
            files_to_transcribe = [{'file':sink.filename,'userID':user.id,'start':sink.fileStart} for user,sink in session.user_sinks.items()]
            session.stop_recording()
            print("Stopped recording")

            for each in files_to_transcribe:
                if os.path.exists(each['file']):
                    await apiClient.transcribe_file(each['file'],each['userID'],session,each['start'])
                    print(f"Transcribed file: {each['file']}")
        else:
            await interaction.response.send_message("What? I'm not listening right now.")
        print("Stop command finished")

    @app_commands.command(name="done", description="Completes the session. Glyph will leave the channel and prepare his notes.")
    async def done(self, interaction: discord.Interaction) -> None:
        print("Finishing")
        session = self.bot.sessions.get(interaction.guild_id)
        if session:
            await interaction.response.send_message("All done! I'll start working on my notes for this session.")
            if session.is_recording():
                print("Session is recording, need to stop")
                session.voice_client.stop_listening()
                files_to_transcribe = [{'file':sink.filename,'userID':user.id,'start':sink.fileStart} for user,sink in session.user_sinks.items()]
                session.stop_recording()
                print("Stopped recording")
                for each in files_to_transcribe:
                    if os.path.exists(each['file']):
                        await apiClient.transcribe_file(each['file'],each['userID'],session,each['start'])
                        print(f"Transcribed file: {each['file']}")
            del self.bot.sessions[interaction.guild_id]
            print("Session deleted")
            await session.voice_client.disconnect()
            await combine_transcripts(session=session,bot=self.bot)
            notes = await apiClient.generate_notes(session=session)
            await interaction.followup.send("Notes are ready!")
            try:
                if len(notes) <= MAX_MESSAGE_LENGTH:
                    print("Notes not too long")
                    await interaction.followup.send(notes)
                else:
                    note_path = f'notes/{session.guild_id}_{session.campaign_id}_{session.session_number}_summary.txt'
                    print(f"Notes too long, note filepath is {note_path}")
                    await interaction.followup.send(content="Too many notes to type! I put them in a file for you.",
                                                file=discord.File(note_path))
            except Exception as e:
                    print(f"Failed to send notes: {e}")
                    return
        else:
            await interaction.response.send_message("I don't have anything to wrap up but alrighty.")
        print("Done command finished")

    @app_commands.command(name="leave", description="Tells Glyph to leave the voice channel.")
    async def leave(self, interaction: discord.Interaction) -> None:
        print("Leaving")
        session = self.bot.sessions.get(interaction.guild_id)
        if session:
            if session.is_recording():
                await self.stop(interaction)
            await session.voice_client.disconnect()
            await interaction.response.send_message("Ok bye!")
        else:
            await interaction.response.send_message("I can't leave something I'm not in!")
        print("Leave command finished")

async def combine_transcripts(session=None, guild_id=None, campaign_id=None, session_number=None, user_id=None,bot=None):
    print("Combining!")
    if bot is None:
        print("Need bot!")
        return -1

    if session is not None:
        guild_id = getattr(session, 'guild_id', guild_id)
        campaign_id = getattr(session, 'campaign_id', campaign_id)
        session_number = getattr(session, 'session_number', session_number)

    transcript_file = f'transcripts/{guild_id}_{campaign_id}_{session_number}.json'
    print(f"Working with transcript file {transcript_file}")

    if os.path.exists(transcript_file):
        with open(transcript_file, "r") as json_file:
            session_transcripts = json.load(json_file) 
    else:
        print(f"No transcripts located for filepath {transcript_file}")
        return -1

    all_segments = []
    nameRef = {}
    async with bot.db.acquire() as conn:
            async with conn.cursor() as cursor:
                try:
                    await cursor.execute(
                        "SELECT gm_id FROM campaigns WHERE campaign_id = ?",
                        (campaign_id,)
                    )
                    gm_entry = await cursor.fetchone()
                    if gm_entry:
                        gm_id = gm_entry[0]
                        nameRef[str(gm_id)] = "DM"
                    
                    await cursor.execute(
                        "SELECT player_id, character_name FROM players WHERE campaign_id = ?",
                        (campaign_id,)
                    )
                    player_entries = await cursor.fetchall()
                    for player_id, character_name in player_entries:
                        nameRef[str(player_id)] = character_name
                except Exception as e:
                    print(f"Query for DM/player data failed: {e}")
                    return
    print("Retrieved DM/Player data:",nameRef)
    for user_id, user_transcripts in session_transcripts.items():
        for session_segments in user_transcripts:
            for segment in session_segments:
                segment_with_user = {
                    'name': nameRef.get(str(user_id), str(user_id)),
                    'start_seconds': segment['start_seconds'],
                    'end_seconds': segment['end_seconds'],
                    'text': segment['text']
                }
                all_segments.append(segment_with_user)

    all_segments_sorted = sorted(all_segments, key=lambda x: x['start_seconds'])
    print("Segments sorted!",all_segments_sorted)
    async with aiofiles.open(f'transcripts/{guild_id}_{campaign_id}_{session_number}_sorted.json', "w") as output_file:
        json_string = json.dumps(all_segments_sorted, indent=4)
        await output_file.write(json_string)
    async with aiofiles.open(f'notes/{guild_id}_{campaign_id}_{session_number}_transcript.txt', 'w') as file:
        for segment in all_segments_sorted:
            line = f"{segment['name']} - {segment['start_seconds']}:{segment['text']}\n"
            await file.write(line)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Recorder(bot))
