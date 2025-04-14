from livekit.agents import Agent, AgentSession, RoomInputOptions
from livekit.plugins import openai, elevenlabs, deepgram, noise_cancellation, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from mosaic_prompt import MOSAIC_PROMPT
from livekit.agents import stt, llm, tts, vad
from dotenv import load_dotenv
import logging

load_dotenv(dotenv_path=".env.local")
logger = logging.getLogger("voice-agent")

from typing import Any

# Define the Agent

class MosaicAgent(Agent):
    def __init__(self, instructions: str, stt: stt.STT, llm: llm.LLM, tts: tts.TTS, vad: vad.VAD, turn_detection: Any, name: str, company: str):
        super().__init__(instructions=instructions, stt=stt, llm=llm, tts=tts, vad=vad, turn_detection=turn_detection)
        self.name = name
        self.company = company

    async def on_enter(self) -> None:
        return self.session.say(f"Hi, I am {self.name} from {self.company}. How can I help you today?")

    async def on_exit(self) -> None:
        return self.session.say(f"It was a pleasure talking to you! Thank you! Have a great day!")










async def entrypoint(ctx: JobContext):
    await ctx.connect()
    session = AgentSession(
        stt=deepgram.STT(),
        llm=openai.LLM(),
        tts=elevenlabs.TTS(),
        vad=silero.VAD.load(),
        turn_detection=MultilingualModel()
    )
    await session.start(
        room=ctx.room,
        agent=Agent(instructions=MOSAIC_PROMPT),
    room_input_options=RoomInputOptions(
        noise_cancellation=noise_cancellation.BVC(),
    ),
)