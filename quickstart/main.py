from dotenv import load_dotenv

from livekit import agents
from livekit.agents import AgentSession, Agent, RoomInputOptions
from livekit.plugins import (
    openai,
    deepgram,
    noise_cancellation,
    silero,
    elevenlabs
)
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from mosaic_prompt import MOSAIC_PROMPT

import logging

load_dotenv(dotenv_path=".env.local")
logger = logging.getLogger("voice-agent")


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=MOSAIC_PROMPT)


async def entrypoint(ctx: agents.JobContext):

    try:
        await ctx.connect()

        session = AgentSession(
        stt=deepgram.STT(model="nova-3", language="multi"),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=elevenlabs.TTS(voice_id="ZUrEGyu8GFMwnHbvLhv2", model="eleven_flash_v2_5", voice_settings=elevenlabs.VoiceSettings(stability=0.4, similarity_boost=0.7, speed=0.9)),
        vad=silero.VAD.load(),
        turn_detection=MultilingualModel(),
    )

        await session.start(
        room=ctx.room,
        agent=Assistant(),
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )

        await session.say("Hi, I am Monika from Mosaic investments. How can I help you today?", allow_interruptions=False)
    except Exception as e:
        logger.error(f"Failed to connect to room: {e}")
        return

if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))