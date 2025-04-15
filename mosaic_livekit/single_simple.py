from livekit.agents import Agent, AgentSession, RoomInputOptions, JobContext, cli, ModelSettings, metrics, WorkerOptions
from livekit.plugins import openai, elevenlabs, deepgram, noise_cancellation, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from mosaic_prompt import MOSAIC_PROMPT
from livekit.agents.llm import ChatContext, ChatMessage, LLM, ChatChunk, FunctionTool
from livekit.agents.tts import TTS
from livekit.agents.vad import VAD
from livekit.agents.stt import STT
from livekit import rtc
from livekit.agents.metrics import LLMMetrics, STTMetrics, EOUMetrics, TTSMetrics
import asyncio
from typing import Any
from rich.table import Table
from dotenv import load_dotenv
import logging
from collections.abc import AsyncIterable, AsyncIterator
from datetime import datetime
from rich.console import Console
from rich import box
import re

load_dotenv(dotenv_path=".env.local")
logger = logging.getLogger("voice-agent")

console = Console()

# Define the Agent

class MosaicAgent(Agent):
    def __init__(self, instructions: str, stt: STT, llm: LLM, tts: TTS, vad: VAD, turn_detection: Any, name: str, company: str):
        super().__init__(instructions=instructions, stt=stt, llm=llm, tts=tts, vad=vad, turn_detection=turn_detection)
        self.name = name
        self.company = company


        def stt_wrapper(metrics: STTMetrics):
            asyncio.create_task(self.on_stt_metrics_collected(metrics))
        
        def llm_wrapper(metrics: LLMMetrics):
            asyncio.create_task(self.on_llm_metrics_collected(metrics))
            
        def eou_wrapper(metrics: EOUMetrics):
            asyncio.create_task(self.on_eou_metrics_collected(metrics))

        def tts_wrapper(metrics: TTSMetrics):
            asyncio.create_task(self.on_tts_metrics_collected(metrics))
            
        self.tts.on("metrics_collected", tts_wrapper)
        self.llm.on("metrics_collected", llm_wrapper)
        self.stt.on("metrics_collected", stt_wrapper)
        self.stt.on("eou_metrics_collected", eou_wrapper)


    async def on_llm_metrics_collected(self, metrics: LLMMetrics) -> None:
        table = Table(
            title="[bold blue]LLM Metrics Report[/bold blue]",
            box=box.ROUNDED,
            highlight=True,
            show_header=True,
            header_style="bold cyan"
        )
        
        table.add_column("Metric", style="bold green")
        table.add_column("Value", style="yellow")
        
        timestamp = datetime.fromtimestamp(metrics.timestamp).strftime('%Y-%m-%d %H:%M:%S')
        
        table.add_row("Type", str(metrics.type))
        table.add_row("Label", str(metrics.label))
        table.add_row("Request ID", str(metrics.request_id))
        table.add_row("Timestamp", timestamp)
        table.add_row("Duration", f"[white]{metrics.duration:.4f}[/white]s")
        table.add_row("Time to First Token", f"[white]{metrics.ttft:.4f}[/white]s")
        table.add_row("Cancelled", "✓" if metrics.cancelled else "✗")
        table.add_row("Completion Tokens", str(metrics.completion_tokens))
        table.add_row("Prompt Tokens", str(metrics.prompt_tokens))
        table.add_row("Total Tokens", str(metrics.total_tokens))
        table.add_row("Tokens/Second", f"{metrics.tokens_per_second:.2f}")
        
        console.print("\n")
        console.print(table)
        console.print("\n")

    async def on_stt_metrics_collected(self, metrics: STTMetrics) -> None:
        table = Table(
            title="[bold blue]STT Metrics Report[/bold blue]",
            box=box.ROUNDED,
            highlight=True,
            show_header=True,
            header_style="bold cyan"
        )
        
        table.add_column("Metric", style="bold green")
        table.add_column("Value", style="yellow")
        
        timestamp = datetime.fromtimestamp(metrics.timestamp).strftime('%Y-%m-%d %H:%M:%S')
        
        # table.add_row("Type", str(metrics.type))
        # table.add_row("Label", str(metrics.label))
        # table.add_row("Request ID", str(metrics.request_id))
        # table.add_row("Timestamp", timestamp)
        # table.add_row("Duration", f"[white]{metrics.duration:.4f}[/white]s")
        # table.add_row("Speech ID", str(metrics.speech_id))
        # table.add_row("Error", str(metrics.error))
        # table.add_row("Streamed", "✓" if metrics.streamed else "✗")
        # table.add_row("Audio Duration", f"[white]{metrics.audio_duration:.4f}[/white]s")
        console.print(f"STT Metrics:: {metrics}")
        console.print("\n")
        console.print(table)
        console.print("\n")


    async def on_eou_metrics_collected(self, metrics: EOUMetrics) -> None:
        table = Table(
            title="[bold blue]End of Utterance Metrics Report[/bold blue]",
            box=box.ROUNDED,
            highlight=True,
            show_header=True,
            header_style="bold cyan"
        )
        
        table.add_column("Metric", style="bold green")
        table.add_column("Value", style="yellow")
        
        timestamp = datetime.fromtimestamp(metrics.timestamp).strftime('%Y-%m-%d %H:%M:%S')

        
        # table.add_row("Type", str(metrics.type))
        # table.add_row("Label", str(metrics.label))
        # table.add_row("Timestamp", timestamp)
        # table.add_row("End of Utterance Delay", f"[white]{metrics.end_of_utterance_delay:.4f}[/white]s")
        # table.add_row("Transcription Delay", f"[white]{metrics.transcription_delay:.4f}[/white]s")
        table.add_row("Speech ID", str(metrics.speech_id))
        # table.add_row("Error", str(metrics.error))
        
        console.print("\n")
        console.print(table)
        console.print("\n")

    async def on_tts_metrics_collected(self, metrics: TTSMetrics) -> None:
        table = Table(
            title="[bold blue]TTS Metrics Report[/bold blue]",
            box=box.ROUNDED,
            highlight=True,
            show_header=True,
            header_style="bold cyan"
        )
        
        table.add_column("Metric", style="bold green")
        table.add_column("Value", style="yellow")
        
        timestamp = datetime.fromtimestamp(metrics.timestamp).strftime('%Y-%m-%d %H:%M:%S')
        
        # table.add_row("Type", str(metrics.type))
        # table.add_row("Label", str(metrics.label))
        table.add_row("Request ID", str(metrics.request_id))
        table.add_row("Timestamp", timestamp)
        table.add_row("Duration", f"[white]{metrics.duration:.4f}[/white]s")
        # table.add_row("Time to First Token", f"[white]{metrics.ttft:.4f}[/white]s")
        # table.add_row("Cancelled", "✓" if metrics.cancelled else "✗")
        # table.add_row("Completion Tokens", str(metrics.completion_tokens))
        # table.add_row("Prompt Tokens", str(metrics.prompt_tokens))
        # table.add_row("Total Tokens", str(metrics.total_tokens))
        # table.add_row("Tokens/Second", f"{metrics.tokens_per_second:.2f}")
        
        console.print("\n")
        console.print(table)
        console.print("\n")

    async def on_enter(self) -> None:
        return self.session.say(f"Hi, I am {self.name} from {self.company}. How can I help you today?")

    async def stt_node(self, audio: AsyncIterable[rtc.AudioFrame]) -> Optional[AsyncIterable[stt.SpeechEvent]]:
        async def filtered_audio():
            async for frame in audio:
                # Apply some noise filtering logic here
                yield frame
    
        async for event in Agent.default.stt_node(filtered_audio()):
            yield event

    async def on_user_turn_completed(
        self, chat_ctx: ChatContext, new_message: ChatMessage,
    ) -> None:
        console.print(f"153 New Message User: {new_message}")
        console.print(f"153 New Message Text Content: {new_message.content}")
        console.print(f"154 New Message TYPE: {type(new_message)}")

        if isinstance(new_message, str):
            console.print(f"154 New Message si a string User: {new_message}")
            msg = new_message
        elif hasattr(new_message, 'text_content'):
            console.print(f"154 New Message has text content User: {new_message.text_content()}")
            msg = new_message.text_content()
        else:
            console.print(f"154 New Message is neither a string nor has text content User: {type(new_message)}")
            msg = str(new_message)
        msg = '123'
        msg = msg.replace("Mosaiq", "Mosaic").replace("mosaik", "Mosaic").replace("mozaic", "Mosaic").replace("mozaiq", "Mosaic").replace("mozaik", "Mosaic").replace("mozaak", "Mosaic").replace("mozaq", "Mosaic")

        chat_ctx = chat_ctx.copy()
        chat_ctx.add_message(role="user", content=msg)
        await self.update_chat_ctx(chat_ctx)

    async def llm_node(
        self,
        chat_ctx: ChatContext,
        tools: list[FunctionTool],
        model_settings: ModelSettings
    ) -> AsyncIterable[ChatChunk]:
        console.print(f"177 LLM Node Chat Context: {chat_ctx}")
        console.print(f"177 LLM Node Tools: {tools}")
        console.print(f"177 LLM Node Model Settings: {model_settings}")
        
        # Process with base LLM implementation
        async for chunk in Agent.default.llm_node(self, chat_ctx=chat_ctx, tools=tools, model_settings=model_settings):
            # Do something with the LLM output before sending it to the next node
            # Process the content to remove markdown delimiters
            if hasattr(chunk, 'delta') and hasattr(chunk.delta, 'content') and chunk.delta.content is not None:
                chunk.delta.content = chunk.delta.content.replace("*", "").replace("#", "").replace("_", "").replace("`", "")
            elif isinstance(chunk, str):
                chunk = chunk.replace("*", "").replace("#", "").replace("_", "").replace("`", "")
            
            print(f"Processing LLM chunk: {chunk}")
            print(f"Chunk type: {type(chunk)}")
            yield chunk

    async def tts_node(
        self,
        text: AsyncIterable[str],
        model_settings: ModelSettings
    ) -> AsyncIterable[rtc.AudioFrame]:
        """
        Process text-to-speech with custom pronunciation rules before synthesis.
        Adjusts common technical terms and abbreviations for better pronunciation.
        """
        # Dictionary of pronunciation replacements.
        # Support for custom pronunciations depends on the TTS provider.
        # To learn more, see the Speech documentation:
        # https://docs.livekit.io/agents/build/speech/#pronunciation.
        pronunciations = {
            "MD": "M D",
            "REST": "rest",
            "AUM": "A U M",
            "ABSL MF": "A B S L M F",
            "kubectl": "kube control",
            "ILFS": "I L F S",
            "PGDBM": "P G D B M",
            "FRM": "F R M",
            "AWS": "A W S",
            "AMC": "A M C",
            "UI": "U I",
            "URL": "U R L",
            "npm": "N P M",
            "LiveKit": "Live Kit",
            "async": "a sink",
            "nginx": "engine x",
        }
    
        async def adjust_pronunciation(input_text: AsyncIterable[str]) -> AsyncIterable[str]:
            async for chunk in input_text:
                modified_chunk = chunk
            
            # Apply pronunciation rules
            for term, pronunciation in pronunciations.items():
                # Use word boundaries to avoid partial replacements
                modified_chunk = re.sub(
                    rf'\b{term}\b',
                    pronunciation,
                    modified_chunk,
                    flags=re.IGNORECASE
                )
            
            yield modified_chunk
    
        # Process with modified text through base TTS implementation
        async for frame in Agent.default.tts_node(self,
            text=adjust_pronunciation(text),
            model_settings=model_settings
        ):
            yield frame

    # async def transcription_node(self, text: AsyncIterable[str]) -> AsyncIterable[str]:    
    #     async def cleanup_text(text_chunk: str) -> str:
    #         # Strip any unwanted formatting
    #         return text_chunk

    #     async for delta in text:
    #         yield cleanup_text(delta)
        

    async def on_exit(self) -> None:
        return self.session.say(f"It was a pleasure talking to you! Thank you! Have a great day!")


async def entrypoint(ctx: JobContext):
    await ctx.connect()
    session = AgentSession()

    # # Use the usage collector to aggregate agent usage metrics
    # usage_collector = metrics.UsageCollector()  

    await session.start(
        room=ctx.room,
        agent=MosaicAgent(
            instructions=MOSAIC_PROMPT, 
            stt=deepgram.STT(),
            llm=openai.LLM(),
            tts=elevenlabs.TTS(voice_id="ODq5zmih8GrVes37Dizd", model="eleven_multilingual_v2"),
            vad=silero.VAD.load(),
            turn_detection=MultilingualModel(), 
            name="Monika", 
            company="Mosaic"),
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )

if __name__ == "__main__":
    cli.run_app(WorkerOptions(
        entrypoint_fnc=entrypoint)
    )    