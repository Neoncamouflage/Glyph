import json
import os
import aiofiles
import asyncio
from datetime import timedelta
from openai import AsyncOpenAI
with open('config.json', 'r') as config_file:
    config = json.load(config_file)


TERMS = ['DnD','Roll20','Glyph','AC','HP']
client = AsyncOpenAI(api_key=config['openai_key'])
file_lock = asyncio.Lock()

def seconds_to_hhmm(seconds):
    elapsed_time = timedelta(seconds=seconds)
    hours, remainder = divmod(elapsed_time.seconds, 3600)
    minutes = remainder // 60
    return f"{hours:02}:{minutes:02}"

async def generate_notes(session=None, guild_id=None, campaign_id=None, session_number=None, user_id=None, note_type='summary',character=None):
    print("Generating notes!")
    noteRef = {'summary':"You are reviewing audio transcripts from a Dungeons and Dragons session for the purpose of summarizing events and highlighting key or memorable moments. You are also recording these notes to help the party keep track of storylines/quests, people they meet and who they are, etc.",
               'character':f"You are reviewing audio transcripts from a Dungeons and Dragons session for the purpose of summarizing events and highlighting key or memorable moments for {character}. Any important actions, results, events, conversations, or similar useful information should be noted."
               }
    try:
        if session is not None:
            print("Session found")
            guild_id = getattr(session, 'guild_id', guild_id)
            campaign_id = getattr(session, 'campaign_id', campaign_id)
            session_number = getattr(session, 'session_number', session_number)
        #Get the recorded transcript
        textFile = f'notes/{guild_id}_{campaign_id}_{session_number}_transcript.txt'
        print(f"Working with textfile {textFile}")
        async with aiofiles.open(textFile, 'r') as file:
            content = await file.read()
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": noteRef[note_type]},
                {"role": "user", "content": f"{content}"}
            ]
        )
        notes = response.choices[0].message.content
        print("Content returned")
        if notes is None:
            print("Notes empty!")
            return -1
        

        async with aiofiles.open(f'notes/{guild_id}_{campaign_id}_{session_number}_summary.txt', 'w') as file:
            await file.write(notes)


    except Exception as e:
        print(f"Error during transcription: {e}")
        return None


async def transcribe_file(file_path,userID,session,fileStart):
    print(f"Transcribing {file_path}")
    userID = str(userID)
    try:
        #Ensure the transcripts directory exists
        transcripts_dir = 'transcripts'
        if not os.path.exists(transcripts_dir):
            os.makedirs(transcripts_dir)
        #Get the path for this session's transcripts
        #Transcript structure is guildID_campaignID_sessionID.json
        session_transcript_filename = f'transcripts/{session.guild_id}_{session.campaign_id}_{session.session_number}.json'
        #Load existing transcriptions or initialize a new structure
        async with file_lock:
            if os.path.exists(session_transcript_filename):
                async with aiofiles.open(session_transcript_filename, "r") as json_file:
                    file_content = await json_file.read()
                    all_transcripts = json.loads(file_content)
            else:
                all_transcripts = {}

            with open(file_path, "rb") as audio_file:
                transcript = await client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    prompt="Umm, let me think like, hmm... Okay, here's what I'm, like, thinking. Roll a D20, yeah, and see what you get.",
                    response_format="verbose_json",
                    language="en"
                )
            
            if transcript is not None:
                # Append the transcription results to the user's data in the global file
                if userID not in all_transcripts:
                    all_transcripts[userID] = []
                print(transcript)
                segData = [
                    {
                        'start_seconds': round(segment['start'] + (fileStart - session.session_start),2),  # Raw start time in seconds for sorting
                        'end_seconds': round(segment['end'] + (fileStart - session.session_start),2),      # Raw end time in seconds for sorting
                        'text': segment['text']
                    }
                    for segment in transcript.segments
                ]
                print(segData)
                all_transcripts[userID].append(segData)
                
                # Save the updated transcriptions back to the single JSON file
                async with aiofiles.open(session_transcript_filename, "w") as json_file:
                    json_string = json.dumps(all_transcripts, indent=4)
                    await json_file.write(json_string)
                
                print(f"Transcription complete for {file_path}, saved to {session_transcript_filename}")
            else:
                print(f"Failed to transcribe {file_path}")
    except Exception as e:
        print(f"Error during transcription: {e}")
        return None

#asyncio.run(transcribe_file('5_1_neoncamouflage_1.mp3'))

'''



async def transcribe_file(file_path, output_dir="transcripts"):
    print("Here in the main")
    loop = asyncio.get_event_loop()
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Transcribe the file asynchronously
    transcript = await loop.run_in_executor(None, transcribe_file_sync, file_path)
    print("Transfcript here")
    if transcript is not None:
        output_filename = os.path.join(output_dir, os.path.basename(file_path).replace(".mp3", "_transcript.txt"))
        with open(output_filename, "w") as file:
            file.write(transcript['text'])
        
        print(f"Transcription complete for {file_path}, written to {output_filename}")
    else:
        print(f"Failed to transcribe {file_path}")

    return transcript'''