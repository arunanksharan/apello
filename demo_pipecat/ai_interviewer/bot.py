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
from pipecat.services.elevenlabs import ElevenLabsTTSService
from pipecat.transports.services.daily import DailyParams, DailyTransport
from mosaic_prompt import MOSAIC_PROMPT
from ai_interviewer import BCG_INTERVIEWER

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


async def get_article_content(prompt, url: str, aiohttp_session: aiohttp.ClientSession):
    # if "arxiv.org" in url:
    #     return await get_arxiv_content(url, aiohttp_session)
    # else:
    #     return await get_wikipedia_content(url, aiohttp_session)
    return prompt


# Helper function to extract content from Wikipedia url (this is
# technically agnostic to URL type but will work best with Wikipedia
# articles)


async def get_wikipedia_content(url: str, aiohttp_session: aiohttp.ClientSession):
    async with aiohttp_session.get(url) as response:
        if response.status != 200:
            return "Failed to download Wikipedia article."

        text = await response.text()
        soup = BeautifulSoup(text, "html.parser")

        content = soup.find("div", {"class": "mw-parser-output"})

        if content:
            return content.get_text()
        else:
            return "Failed to extract Wikipedia article content."


# Helper function to extract content from arXiv url


async def get_arxiv_content(url: str, aiohttp_session: aiohttp.ClientSession):
    if "/abs/" in url:
        url = url.replace("/abs/", "/pdf/")
    if not url.endswith(".pdf"):
        url += ".pdf"

    async with aiohttp_session.get(url) as response:
        if response.status != 200:
            return "Failed to download arXiv PDF."

        content = await response.read()
        pdf_file = io.BytesIO(content)
        pdf_reader = PdfReader(pdf_file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text()
        return text


# This is the main function that handles STT -> LLM -> TTS


async def main():
    url = input("Enter the URL of the article you would like to talk about: ")

    async with aiohttp.ClientSession() as session:
        article_content = await get_article_content(BCG_INTERVIEWER, url, session)
        # article_content = truncate_content(article_content, model_name="gpt-4o-mini")

        (room_url, token) = await configure(session)

        transport = DailyTransport(
            room_url,
            token,
            "studypal",
            DailyParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                transcription_enabled=True,
                vad_analyzer=SileroVADAnalyzer(),
            ),
        )

        # tts = CartesiaTTSService(
        #     api_key=os.getenv("CARTESIA_API_KEY"),
        #     voice_id=os.getenv("CARTESIA_VOICE_ID", "4d2fd738-3b3d-4368-957a-bb4805275bd9"),
        #     # British Narration Lady: 4d2fd738-3b3d-4368-957a-bb4805275bd9
        # )

        elevenlabs_tts = ElevenLabsTTSService(
            api_key=os.getenv("ELEVEN_API_KEY"),
            voice_id=os.getenv("ELEVEN_VOICE_ID"),
            sample_rate=16000,
        )

        llm = OpenAILLMService(api_key=os.getenv("OPENAI_API_KEY"), model="gpt-4.1-mini")

        messages = [
            {
                "role": "system",
                "content": f"""

{article_content}


""",
            },
        ]

        context = OpenAILLMContext(messages)
        context_aggregator = llm.create_context_aggregator(context)

        pipeline = Pipeline(
            [
                transport.input(),
                context_aggregator.user(),
                llm,
                elevenlabs_tts,
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
            await transport.capture_participant_transcription(participant["id"])
            messages.append(
                {
                    "role": "user",
                    "content": "Hello!",
                }
            )
            await task.queue_frames([context_aggregator.user().get_context_frame()])

        @transport.event_handler("on_participant_left")
        async def on_participant_left(transport, participant, reason):
            await task.cancel()

        runner = PipelineRunner()

        await runner.run(task)


if __name__ == "__main__":
    asyncio.run(main())
