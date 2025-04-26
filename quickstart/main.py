import os
import pprint
from dotenv import load_dotenv
import jwt
import uuid
import time


print("\n=== ENVIRONMENT VARIABLES AT RUNTIME ===")
pprint.pprint(dict(os.environ))
print("=== END ENVIRONMENT VARIABLES ===\n")

if os.path.exists(".env.local"):
    print("Loading .env.local file")
    load_dotenv(dotenv_path=".env.local")
else:
    print(".env.local file not found; relying on environment variables only")

from livekit.agents import Agent, AgentSession, RoomInputOptions, JobContext, cli, ModelSettings, metrics, WorkerOptions, RoomOutputOptions
from livekit.plugins import openai, elevenlabs, deepgram, noise_cancellation, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from mosaic_prompt import MOSAIC_PROMPT
from livekit.agents.llm import ChatContext, ChatMessage, LLM, ChatChunk, FunctionTool
from livekit.agents.tts import TTS
from livekit.agents.vad import VAD
from livekit.agents.stt import STT, SpeechEvent
from livekit.rtc import AudioFrame, TrackPublishOptions, TrackSource, LocalAudioTrack, Room
from livekit.agents.metrics import LLMMetrics, STTMetrics, EOUMetrics, TTSMetrics
from livekit.agents.stt import SpeechEventType

import asyncio
from typing import Any, Optional
from rich.table import Table
import logging
from collections.abc import AsyncIterable, AsyncIterator
from datetime import datetime
from rich.console import Console
from rich import box
import re
from livekit.rtc import AudioSource
from livekit.api import AccessToken, VideoGrants
from datetime import timedelta
from aura import AI_ASTROLOGY


# Create two independent AudioSources:
mic_source = AudioSource(sample_rate=24000, num_channels=1)
tts_sink   = AudioSource(sample_rate=24000, num_channels=1)



logger = logging.getLogger("voice-agent")

logger.setLevel(logging.DEBUG)
logger.debug("Starting application...")
logger.debug("Loading environment variables...")
logger.debug(f"LK_URL: {os.getenv('LIVEKIT_URL')}")
logger.debug(f"LK_API_KEY: {os.getenv('LIVEKIT_API_KEY')}")
logger.debug(f"LK_API_SECRET: {os.getenv('LIVEKIT_API_SECRET')}")
logger.debug(f"DEEPGRAM_API_KEY: {os.getenv('DEEPGRAM_API_KEY')}")
logger.debug(f"OPENAI_API_KEY: {os.getenv('OPENAI_API_KEY')}")
logger.debug(f"ELEVEN_API_KEY: {os.getenv('ELEVEN_API_KEY')}")
logger.debug(f"SMALLEST_API_KEY: {os.getenv('SMALLEST_API_KEY')}")

console = Console()

for var in ["LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "DEEPGRAM_API_KEY", "OPENAI_API_KEY", "ELEVEN_API_KEY", "SMALLEST_API_KEY"]:
    value = os.getenv(var)
    if value is None:
        print(f"WARNING: {var} is NOT set in environment!")
    else:
        print(f"{var} = {value}")


def generate_room_token1(room: str) -> str:
    """
    Mint a LiveKit JWT for the given room using PyJWT.
    """
    api_key = os.getenv("LIVEKIT_API_KEY")
    api_secret = os.getenv("LIVEKIT_API_SECRET")
    identity = f"agent-{room}"
    now = int(time.time())
    exp = now + 2 * 3600
    jti = str(uuid.uuid4())
    header = {"alg": "HS256", "typ": "JWT", "kid": api_key}
    payload = {
        "iss": api_key,
        "sub": identity,
        "nbf": now,
        "exp": exp,
        "jti": jti,
        "video": {
            "room_join": True,
            "room": room,
        }
    }
    token = jwt.encode(
        payload,
        api_secret,
        algorithm="HS256",
        headers={"kid": api_key},
    )
    # In PyJWT>=2.x encode returns str; if bytes, decode to str
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token


def generate_room_token(room: str) -> str:
    """
    Mint a LiveKit JWT for the given room using the official server SDK.
    """
    from livekit.api.access_token import AccessToken, VideoGrants

    api_key = os.getenv("LIVEKIT_API_KEY")
    api_secret = os.getenv("LIVEKIT_API_SECRET")
    identity = f"agent-{room}"

    # Build token with identity, agent kind, video grant, and TTL
    at = AccessToken(api_key, api_secret)
    at = at.with_identity(identity)
    at = at.with_kind("agent")
    at = at.with_grants(VideoGrants(room_join=True, room=room))
    at = at.with_ttl(timedelta(hours=2))

    jwt_token = at.to_jwt()
    return jwt_token

class KLStreamingAgent(Agent):
    def __init__(self, instructions, stt, llm, tts, vad, turn_detection, name, company):
        super().__init__(instructions=instructions,
                         stt=stt, llm=llm, tts=tts,
                         vad=vad, turn_detection=turn_detection,
                         allow_interruptions=True)
        self.name = name
        self.company = company
        self._interim_buffer = ""
        self._last_update = None
        self._debounce_ms = 400
        self._debounce_task = None
        self._last_sent_text: str = ""

    async def on_enter(self):
        return await self.session.say(
            f"Hi, I am {self.name} from {self.company}. How can I help you?",
            allow_interruptions=False
        )
    
    async def stt_node(
        self,
        audio: AsyncIterable[AudioFrame],
        model_settings,
    ) -> AsyncIterable[SpeechEvent]:
        # use the STT instance you passed in, not re-init
        stt_stream = self.stt.stream()
       

        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._push_audio(audio, stt_stream))

            async for event in stt_stream:
                if not event.alternatives:
                    yield event
                    continue

                text = event.alternatives[0].text

                if event.type == SpeechEventType.INTERIM_TRANSCRIPT:
                    if self._debounce_task and not self._debounce_task.done():
                        self._debounce_task.cancel()
                    self._interim_buffer = text
                    self._last_update = asyncio.get_event_loop().time()
                    self._debounce_task = asyncio.create_task(
                        self._debounce_send_to_llm()
                    )

                elif event.type == SpeechEventType.FINAL_TRANSCRIPT:
                    if self._debounce_task and not self._debounce_task.done():
                        self._debounce_task.cancel()
                    await self._send_to_llm(text, final=True)
                    self._interim_buffer = ""
                    self._last_update = None

                yield event

    async def _push_audio(self, audio: AsyncIterable[AudioFrame], stt_stream):
        """
        Push each AudioFrame directly to the STT stream.
        """
        async for audio_frame in audio:
            stt_stream.push_frame(audio_frame)
        stt_stream.end_input()

    async def _debounce_send_to_llm(self):
        await asyncio.sleep(self._debounce_ms / 1000)
        now = asyncio.get_event_loop().time()
        if (
            self._last_update
            and (now - self._last_update) >= (self._debounce_ms / 1000)
            and self._interim_buffer
        ):
            await self._send_to_llm(self._interim_buffer, final=False)
            self._interim_buffer = ""
            self._last_update = None

    def _normalize(self, text: str) -> str:
        return (
            text
            .replace("Mosaiq", "Mosaic")
            .replace("mosaik", "Mosaic")
            .replace("mozaic", "Mosaic")
            .replace("mozaiq", "Mosaic")
            .replace("mozaik", "Mosaic")
            .replace("mozaak", "Mosaic")
            .replace("mozaq", "Mosaic")
        )

    async def _send_to_llm(self, text: str, final: bool):
        normalized = self._normalize(text)
        # feed the normalized user input into the LLM pipeline
        # ➤ skip if it’s identical to the last thing we sent
        if normalized == self._last_sent_text:
            return
        self._last_sent_text = normalized

        # ➤ stop whatever speech is in flight
        if final:
            await self.session.interrupt()
        # 2) Feed the text into the LLM pipeline
        self.session.generate_reply(user_input=normalized, allow_interruptions=True)


    async def llm_node(
        self,
        chat_ctx: ChatContext,
        tools: list[FunctionTool],
        model_settings,
    ) -> AsyncIterable[ChatChunk]:
        console.print(f"LLM context: {chat_ctx}")
        async for chunk in super().llm_node(
            chat_ctx=chat_ctx, tools=tools, model_settings=model_settings
        ):
        # Skip any empty chunks
            if chunk is None:
                continue
            # If it's a ChatChunk with a delta attribute
            delta = getattr(chunk, "delta", None)
            content = getattr(delta, "content", None) if delta else None

            if content:
                # Clean markdown characters
                clean = (
                    content.replace("*", "")
                           .replace("#", "")
                           .replace("_", "")
                           .replace("`", "")
                )
                chunk.delta.content = clean
            elif isinstance(chunk, str):
                chunk = chunk.replace("*", "").replace("#", "").replace("_", "").replace("`", "")
            yield chunk

            # if hasattr(chunk, "delta") and chunk.delta.content:
            #     chunk.delta.content = (
            #         chunk.delta.content
            #         .replace("*", "")
            #         .replace("#", "")
            #         .replace("_", "")
            #         .replace("`", "")
            #     )
            # elif isinstance(chunk, str):
            #     chunk = chunk.replace("*", "").replace("#", "").replace("_", "").replace("`", "")
            # yield chunk

    async def tts_node(
        self,
        text: AsyncIterable[str],
        model_settings,
    ) -> AsyncIterable[AudioFrame]:
        pronunciations = {
            "MD": "M D",
            "REST": "rest",
            "AWS": "A W S",
            "LiveKit": "Live Kit",
            "async": "a sink",
            # …add more…
        }

        async def smooth_and_pron(input_stream: AsyncIterable[str]) -> AsyncIterable[str]:
            buffer = ""
            async for chunk in input_stream:
                buffer += chunk
                if buffer and (buffer[-1] in ".!?," or buffer.endswith(" ")):
                    modified = buffer
                    for term, pron in pronunciations.items():
                        modified = re.sub(
                            rf"\b{term}\b",
                            pron,
                            modified,
                            flags=re.IGNORECASE,
                        )
                    yield modified
                    buffer = ""
            if buffer:
                modified = buffer
                for term, pron in pronunciations.items():
                    modified = re.sub(rf"\b{term}\b", pron, modified, flags=re.IGNORECASE)
                yield modified

        async for frame in super().tts_node(
            text=smooth_and_pron(text),
            model_settings=model_settings,
        ):
            yield frame


    # ... STT, _push_audio, _debounce, normalize, _send_to_llm, llm_node, tts_node as before ...
    # For brevity, assume these methods are identical to the earlier fully-tested versions.
    # Ensure tts_node safely catches CancelledError and other exceptions.


async def entrypoint(ctx: JobContext):
    # 1) register worker with control plane
    await ctx.connect()
    print("Worker registered with control plane")
    print("Worker ID:", ctx.worker_id)
    # 2) determine room name (ctx.room might be a string or a Room object)
    # raw_room = ctx.room
    # if hasattr(raw_room, 'name'):
    #     room_name = raw_room.name
    # else:
    #     room_name = str(raw_room)
    # print("Room name:", room_name)

    # # 2) generate room JWT
    # jwt = generate_room_token(room_name)
    # ws_url = os.getenv("LIVEKIT_URL")

    # 3) manual Room connect for media
    # media_room = Room()
    # await media_room.connect(ws_url, jwt)

    # # 4) create separate audio sources and publish tracks
    # mic_source = AudioSource(sample_rate=24000, num_channels=1)
    # mic_track = LocalAudioTrack.create_audio_track("agent-mic", mic_source)
    # await media_room.local_participant.publish_track(mic_track)

    # tts_sink = AudioSource(sample_rate=24000, num_channels=1)
    # tts_track = LocalAudioTrack.create_audio_track("agent-tts", tts_sink)
    # await media_room.local_participant.publish_track(tts_track)

    # 5) create AgentSession with manual Room
    session = AgentSession(
        stt=deepgram.STT(model="nova-2-general", language="multi", keywords=[("Astrology",20)]),
        llm=openai.LLM(model="gpt-4o-mini", temperature=0.7, timeout=60),
        tts=elevenlabs.TTS(
            model="eleven_flash_v2_5", voice_id=os.getenv("ELEVENLABS_VOICE_ID"),
            voice_settings=elevenlabs.VoiceSettings(0.4, 0.7, 0.9)
        ),
        vad=silero.VAD.load(),
        turn_detection=MultilingualModel(),
        allow_interruptions=True
    )

    # 6) start the agent session (uses custom audio sources/tracks)
    await session.start(
        agent=KLStreamingAgent(
            instructions=AI_ASTROLOGY,
            stt=session.stt,
            llm=session.llm,
            tts=session.tts,
            vad=session.vad,
            turn_detection=session.turn_detection,
            name="Monika",
            company="Aura Numbers",
        ),
        room=ctx.room,
        room_input_options=RoomInputOptions(noise_cancellation=noise_cancellation.BVC()),
        room_output_options=RoomOutputOptions(
        audio_enabled=True,
        # by choosing anything BUT SOURCE_MICROPHONE we get a fresh track
        audio_publish_options=TrackPublishOptions(
            source=TrackSource.SOURCE_UNKNOWN
        )
    ),
    )

    # 7) initial greeting
    # await session.say(
    #     "Hi, I am Monika from Mosaic investments. How can I help you today?",
    #     allow_interruptions=False
    # )

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))



# # ----- Agent Definition -----
# class KLStreamingAgent(Agent):
#     def __init__(
#         self,
#         instructions: str,
#         stt,
#         llm,
#         tts,
#         vad: VAD,
#         turn_detection: Any,
#         name: str,
#         company: str,
#         allow_interruptions: bool = True,
#     ):
#         super().__init__(
#             instructions=instructions,
#             stt=stt,
#             llm=llm,
#             tts=tts,
#             vad=vad,
#             turn_detection=turn_detection,
#             allow_interruptions=allow_interruptions,
#         )
#         self.name = name
#         self.company = company

#         # interim/debounce state
#         self._interim_buffer: str = ""
#         self._last_update: Optional[float] = None
#         self._debounce_ms = 200
#         self._debounce_task: Optional[asyncio.Task] = None

#     async def on_enter(self) -> None:
#         return await self.session.say(
#             f"Hi, I am {self.name} from {self.company}. How can I help you today?"
#         )

    # async def stt_node(
    #     self,
    #     audio: AsyncIterable[AudioFrame],
    #     model_settings,
    # ) -> AsyncIterable[SpeechEvent]:

    # # use the STT instance you passed in, not re-init
    #     stt_stream = self.stt.stream()
       

    #     async with asyncio.TaskGroup() as tg:
    #         tg.create_task(self._push_audio(audio, stt_stream))

    #         async for event in stt_stream:
    #             if not event.alternatives:
    #                 yield event
    #                 continue

    #             text = event.alternatives[0].text

    #             if event.type == SpeechEventType.INTERIM_TRANSCRIPT:
    #                 if self._debounce_task and not self._debounce_task.done():
    #                     self._debounce_task.cancel()
    #                 self._interim_buffer = text
    #                 self._last_update = asyncio.get_event_loop().time()
    #                 self._debounce_task = asyncio.create_task(
    #                     self._debounce_send_to_llm()
    #                 )

    #             elif event.type == SpeechEventType.FINAL_TRANSCRIPT:
    #                 if self._debounce_task and not self._debounce_task.done():
    #                     self._debounce_task.cancel()
    #                 await self._send_to_llm(text)
    #                 self._interim_buffer = ""
    #                 self._last_update = None

    #             yield event

    # async def _push_audio(self, audio: AsyncIterable[AudioFrame], stt_stream):
    #     """
    #     Push each AudioFrame directly to the STT stream.
    #     """
    #     async for audio_frame in audio:
    #         stt_stream.push_frame(audio_frame)
    #     stt_stream.end_input()

    # async def _debounce_send_to_llm(self):
    #     await asyncio.sleep(self._debounce_ms / 1000)
    #     now = asyncio.get_event_loop().time()
    #     if (
    #         self._last_update
    #         and (now - self._last_update) >= (self._debounce_ms / 1000)
    #         and self._interim_buffer
    #     ):
    #         await self._send_to_llm(self._interim_buffer)
    #         self._interim_buffer = ""
    #         self._last_update = None

    # def _normalize(self, text: str) -> str:
    #     return (
    #         text
    #         .replace("Mosaiq", "Mosaic")
    #         .replace("mosaik", "Mosaic")
    #         .replace("mozaic", "Mosaic")
    #         .replace("mozaiq", "Mosaic")
    #         .replace("mozaik", "Mosaic")
    #         .replace("mozaak", "Mosaic")
    #         .replace("mozaq", "Mosaic")
    #     )

    # async def _send_to_llm(self, text: str):
    #     normalized = self._normalize(text)
    #     # feed the normalized user input into the LLM pipeline
    #     # 1) Stop any in-flight TTS immediately:
    #     # await self.session.interrupt()
    #     # 2) Feed the text into the LLM pipeline
    #     self.session.generate_reply(user_input=normalized, allow_interruptions=True)


    # async def llm_node(
    #     self,
    #     chat_ctx: ChatContext,
    #     tools: list[FunctionTool],
    #     model_settings,
    # ) -> AsyncIterable[ChatChunk]:
    #     console.print(f"LLM context: {chat_ctx}")
    #     async for chunk in super().llm_node(
    #         chat_ctx=chat_ctx, tools=tools, model_settings=model_settings
    #     ):
    #     # Skip any empty chunks
    #         if chunk is None:
    #             continue
    #         # If it's a ChatChunk with a delta attribute
    #         delta = getattr(chunk, "delta", None)
    #         content = getattr(delta, "content", None) if delta else None

    #         if content:
    #             # Clean markdown characters
    #             clean = (
    #                 content.replace("*", "")
    #                        .replace("#", "")
    #                        .replace("_", "")
    #                        .replace("`", "")
    #             )
    #             chunk.delta.content = clean
    #         elif isinstance(chunk, str):
    #             chunk = chunk.replace("*", "").replace("#", "").replace("_", "").replace("`", "")
    #         yield chunk

    #         # if hasattr(chunk, "delta") and chunk.delta.content:
    #         #     chunk.delta.content = (
    #         #         chunk.delta.content
    #         #         .replace("*", "")
    #         #         .replace("#", "")
    #         #         .replace("_", "")
    #         #         .replace("`", "")
    #         #     )
    #         # elif isinstance(chunk, str):
    #         #     chunk = chunk.replace("*", "").replace("#", "").replace("_", "").replace("`", "")
    #         # yield chunk

    # async def tts_node(
    #     self,
    #     text: AsyncIterable[str],
    #     model_settings,
    # ) -> AsyncIterable[AudioFrame]:
    #     pronunciations = {
    #         "MD": "M D",
    #         "REST": "rest",
    #         "AWS": "A W S",
    #         "LiveKit": "Live Kit",
    #         "async": "a sink",
    #         # …add more…
    #     }

    #     async def smooth_and_pron(input_stream: AsyncIterable[str]) -> AsyncIterable[str]:
    #         buffer = ""
    #         async for chunk in input_stream:
    #             buffer += chunk
    #             if buffer and (buffer[-1] in ".!?," or buffer.endswith(" ")):
    #                 modified = buffer
    #                 for term, pron in pronunciations.items():
    #                     modified = re.sub(
    #                         rf"\b{term}\b",
    #                         pron,
    #                         modified,
    #                         flags=re.IGNORECASE,
    #                     )
    #                 yield modified
    #                 buffer = ""
    #         if buffer:
    #             modified = buffer
    #             for term, pron in pronunciations.items():
    #                 modified = re.sub(rf"\b{term}\b", pron, modified, flags=re.IGNORECASE)
    #             yield modified

    #     async for frame in super().tts_node(
    #         text=smooth_and_pron(text),
    #         model_settings=model_settings,
    #     ):
    #         yield frame

# # ----- Entrypoint & Session Wiring -----
# async def entrypoint(ctx: JobContext):
#     await ctx.connect()
#     session = AgentSession(
#         allow_interruptions=True,
#         stt=deepgram.STT(model="nova-2-general", 
#             language="multi",
#             interim_results=True,
#             smart_format=True,
#             punctuate=True,
#             keywords=[("Mosaic", 20)]),
#         llm=openai.LLM(
#             model="gpt-4o-mini",
#             temperature=0.7,
#         ),
#         tts=elevenlabs.TTS(
#             model="eleven_multilingual_v2",
#             voice_id=os.getenv("ELEVENLABS_VOICE_ID"),
#             voice_settings=elevenlabs.VoiceSettings(stability=0.4, similarity_boost=0.7, speed=0.9)
#         ),
       
#     )

#     await session.start(
#         room=ctx.room,
#         agent=KLStreamingAgent(
#             instructions=MOSAIC_PROMPT,
#             stt=session.stt,
#             llm=session.llm,
#             tts=session.tts,
#             vad=silero.VAD.load(),
#             turn_detection=MultilingualModel(),
#             name="Monika",
#             company="Mosaic",
#             allow_interruptions=True,
#         ),
#         # audio_source=mic_source,  # STT reads from here
#         # audio_sink=tts_sink,      # TTS writes to here
#         room_input_options=RoomInputOptions(
#             noise_cancellation=noise_cancellation.BVC(),
#         ),
#     #     room_output_options=RoomOutputOptions(
#     # audio_enabled=True,
#     # # Publish TTS on its own track (not the microphone)
#     # audio_publish_options=TrackPublishOptions(
#     #   source=TrackSource.SOURCE_UNKNOWN
#     # )
# #   ),
#     )

# if __name__ == "__main__":
#     cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
