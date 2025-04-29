import asyncio
import io
import os
import sys

import aiohttp
import tiktoken
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from loguru import logger
from pypdf import PdfReader
from runner import configure

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.cartesia import CartesiaTTSService
from pipecat.services.openai import OpenAILLMService
from pipecat.services.deepgram import DeepgramSTTService, LiveOptions
from pipecat.services.elevenlabs import ElevenLabsTTSService, ElevenLabsHttpTTSService

from pipecat.transports.services.daily import DailyParams, DailyTransport
from pipecat.audio.vad.vad_analyzer import VADParams
from prompt import MOSAIC_PROMPT, MOSAIC_PROMPT_TRUNCATED

load_dotenv(override=True)

# Run this script directly from your command line.
# This project was adapted from
# https://github.com/pipecat-ai/pipecat/blob/main/examples/foundational/07d-interruptible-cartesia.py

logger.remove(0)
logger.add(sys.stderr, level="DEBUG")


# Count number of tokens used in model and truncate the content
def truncate_content(content, model_name):
    encoding = tiktoken.encoding_for_model(model_name)
    tokens = encoding.encode(content)

    max_tokens = 10000
    if len(tokens) > max_tokens:
        truncated_tokens = tokens[:max_tokens]
        return encoding.decode(truncated_tokens)
    return content


# Main function to extract content from url


async def get_article_content(prompt, aiohttp_session: aiohttp.ClientSession):
    return prompt

# This is the main function that handles STT -> LLM -> TTS



async def main(agent_name, company_name):
    agent_welcome_message = f"Hello! I am {agent_name} from {company_name}. How can I help you today?"

    async with aiohttp.ClientSession() as session:
        prompt_content = await get_article_content(MOSAIC_PROMPT, session)

        (room_url, token) = await configure(session)

        transport = DailyTransport(
            room_url,
            token,
            "Monika (Mosaic)",
            DailyParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                transcription_enabled=True,
                vad_enabled=True,
                vad_audio_passthrough=True,
                vad_analyzer=SileroVADAnalyzer(
                    sample_rate=16000,
                    params=VADParams(
                        confidence=0.6,
                        min_volume=0.3,
                    ),
                ),
            ),
        )

        # tts = CartesiaTTSService(
        #     api_key=os.getenv("CARTESIA_API_KEY"),
        #     voice_id=os.getenv("CARTESIA_VOICE_ID", "4d2fd738-3b3d-4368-957a-bb4805275bd9"),
        #     # British Narration Lady: 4d2fd738-3b3d-4368-957a-bb4805275bd9
        # )

        stt = DeepgramSTTService(
                api_key=os.getenv("DEEPGRAM_API_KEY"),
                # live_options=LiveOptions(**stt_config_data.get("live_options", {}))
            )

        elevenlabs_http_tts = ElevenLabsHttpTTSService(
            api_key=os.getenv("ELEVEN_API_KEY"),
            voice_id=os.getenv("ELEVEN_VOICE_ID"),
            sample_rate=16000,
            aiohttp_session=session,
        )
        elevenlabs_tts = ElevenLabsTTSService(
            api_key=os.getenv("ELEVEN_API_KEY"),
            voice_id=os.getenv("ELEVEN_VOICE_ID"),
            sample_rate=16000,
            params=ElevenLabsTTSService.InputParams(speed=0.9),
        )

        llm = OpenAILLMService(api_key=os.getenv("OPENAI_API_KEY"), model="gpt-4.1-mini")

        messages = [
            {
                "role": "system",
                "content": f"""

{prompt_content}


""",
            },
        ]

        context = OpenAILLMContext(messages)
        context_aggregator = llm.create_context_aggregator(context)

        pipeline = Pipeline(
            [
                transport.input(),
                stt,
                context_aggregator.user(),
                llm,
                elevenlabs_http_tts,
                transport.output(),
                context_aggregator.assistant(),
            ]
        )

        task = PipelineTask(
            pipeline,
            params=PipelineParams(
                audio_out_sample_rate=44100,
                allow_interruptions=True,
                enable_metrics=True,
            ),
        )

        @transport.event_handler("on_first_participant_joined")
        async def on_first_participant_joined(transport, participant):
            # await transport.capture_participant_transcription(participant["id"])
            messages.append(
                {"role": "system", "content": f"Introduce yourself by saying this as it is: '{agent_welcome_message}'"}
            )
            await task.queue_frames([context_aggregator.user().get_context_frame()])

        @transport.event_handler("on_participant_left")
        async def on_participant_left(transport, participant, reason):
            await task.cancel()

        runner = PipelineRunner()

        await runner.run(task)


if __name__ == "__main__":
    asyncio.run(main("Monika", "Mosaic Investments"))
