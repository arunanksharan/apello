import logging

from dotenv import load_dotenv
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    llm,
    metrics,
)
from livekit.plugins import elevenlabs
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.plugins import (
    cartesia,
    openai,
    deepgram,
    noise_cancellation,
    silero,
    elevenlabs,
    turn_detector,
)
from mosaic_prompt import MOSAIC_PROMPT


load_dotenv(dotenv_path=".env.local")
logger = logging.getLogger("voice-agent")


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


class LLMOutputProcessedVoiceAgent(VoicePipelineAgent):
    def __init__(self, **kwargs) -> None:
        super().__init__(
            **kwargs
        #     instructions="""
        #         You are a helpful agent that thinks through problems step by step.
        #         When reasoning through a complex question, wrap your thinking in <think></think> tags.
        #         After you've thought through the problem, provide your final answer.
        #     """,
        #     stt=deepgram.STT(),
        #     llm=openai.LLM.with_groq(model="deepseek-r1-distill-llama-70b"),
        #     tts=openai.TTS(),
        #     vad=silero.VAD.load()
        )
    
    # async def on_enter(self):
    #     self.session.generate_reply()

    async def llm_node(
        self, chat_ctx, tools, model_settings=None
    ):
        activity = self._Agent__get_activity_or_raise()
        assert activity.llm is not None, "llm_node called but no LLM node is available"
        
        async def process_stream():
            async with activity.llm.chat(chat_ctx=chat_ctx, tools=tools, tool_choice=None) as stream:
                async for chunk in stream:
                    print(f"chunk in llm node: {chunk}")
                    if chunk is None:
                        continue

                    content = getattr(chunk.delta, 'content', None) if hasattr(chunk, 'delta') else str(chunk)
                    if content is None:
                        yield chunk
                        continue

                    processed_content = content.replace("*", "").replace("#", "")

                    if processed_content != content:
                        if hasattr(chunk, 'delta') and hasattr(chunk.delta, 'content'):
                            chunk.delta.content = processed_content
                        else:
                            chunk = processed_content

                    yield chunk



async def entrypoint(ctx: JobContext):
    initial_ctx = llm.ChatContext().append(
        role="system",
        text=MOSAIC_PROMPT,
    )

    logger.info(f"connecting to room {ctx.room.name}")
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Wait for the first participant to connect
    participant = await ctx.wait_for_participant()
    logger.info(f"starting voice assistant for participant {participant.identity}")

    # This project is configured to use Deepgram STT, OpenAI LLM and Cartesia TTS plugins
    # Other great providers exist like Cerebras, ElevenLabs, Groq, Play.ht, Rime, and more
    # Learn more and pick the best one for your app:
    # https://docs.livekit.io/agents/plugins
    agent = VoicePipelineAgent(
        vad=ctx.proc.userdata["vad"],
        stt=deepgram.STT(),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=elevenlabs.TTS(voice_id="6ZUrEGyu8GFMwnHbvLhv2", model="eleven_flash_v2_5"),
        # use LiveKit's transformer-based turn detector
        turn_detector=turn_detector.EOUModel(),
        # minimum delay for endpointing, used when turn detector believes the user is done with their turn
        min_endpointing_delay=0.5,
        # maximum delay for endpointing, used when turn detector does not believe the user is done with their turn
        max_endpointing_delay=5.0,
        # enable background voice & noise cancellation, powered by Krisp
        # included at no additional cost with LiveKit Cloud
        noise_cancellation=noise_cancellation.BVC(),
        chat_ctx=initial_ctx,
    )

    usage_collector = metrics.UsageCollector()

    @agent.on("metrics_collected")
    def on_metrics_collected(agent_metrics: metrics.AgentMetrics):
        metrics.log_metrics(agent_metrics)
        usage_collector.collect(agent_metrics)

    agent.start(ctx.room, participant)

    # The agent should be polite and greet the user when it joins :)
    await agent.say("Hi, I am Priyansh from Mosaic investments. How can I help you today?", allow_interruptions=True)


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        ),
    )
