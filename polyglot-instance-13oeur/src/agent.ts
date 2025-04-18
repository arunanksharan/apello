// SPDX-FileCopyrightText: 2024 LiveKit, Inc.
//
// SPDX-License-Identifier: Apache-2.0
import {
  type JobContext,
  type JobProcess,
  WorkerOptions,
  cli,
  defineAgent,
  llm,
  pipeline,
} from '@livekit/agents';
import * as deepgram from '@livekit/agents-plugin-deepgram';
import * as elevenlabs from '@livekit/agents-plugin-elevenlabs';
import * as openai from '@livekit/agents-plugin-openai';
import * as silero from '@livekit/agents-plugin-silero';
import dotenv from 'dotenv';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import MOSAIC_PROMPT from './mosaic-agent.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const envPath = path.join(__dirname, '../.env.local');
dotenv.config({ path: envPath });

export default defineAgent({
  prewarm: async (proc: JobProcess) => {
    proc.userData.vad = await silero.VAD.load();
  },
  entry: async (ctx: JobContext) => {
    try {
      const vad = ctx.proc.userData.vad! as silero.VAD;
      const initialContext = new llm.ChatContext().append({
        role: llm.ChatRole.SYSTEM,
        text: MOSAIC_PROMPT,
      });

      await ctx.connect();
      console.log('waiting for participant');
      const participant = await ctx.waitForParticipant();
      console.log(`starting assistant example agent for ${participant.identity}`);

      // const fncCtx: llm.FunctionContext = {
      //   weather: {
      //     description: 'Get the weather in a location',
      //     parameters: z.object({
      //       location: z.string().describe('The location to get the weather for'),
      //     }),
      //     execute: async ({ location }) => {
      //       console.debug(`executing weather function for ${location}`);
      //       const response = await fetch(`https://wttr.in/${location}?format=%C+%t`);
      //       if (!response.ok) {
      //         throw new Error(`Weather API returned status: ${response.status}`);
      //       }
      //       const weather = await response.text();
      //       return `The weather in ${location} right now is ${weather}.`;
      //     },
      //   },
      // };

      const agent = new pipeline.VoicePipelineAgent(
        vad,
        new deepgram.STT({
          language: 'en-IN',
          // detectLanguage: true,
          // punctuate: true,
          // smartFormat: true,
          // profanityFilter: true,
          // dictation: true,
          // diarize: true,
          // numerals: true,
          // keywords: [],
          // endpointing: 0.3,
          // fillerWords: true,
          // interimResults: true,
          // sampleRate: 44100,
          // numChannels: 1,
          // model: 'nova-3-general',
        }),
        new openai.LLM({ model: 'gpt-4o-mini' }),
        new elevenlabs.TTS({
          voice: {
            id: 'd0grukerEzs069eKIauC',
            name: 'Monica',
            category: 'premade',
            settings: {
              stability: 0.4,
              similarity_boost: 0.7,
              style: 0.7,
              use_speaker_boost: true,
            },
          },
          modelID: 'eleven_flash_v2_5',
          // encoding: 'pcm_44100',
          // languageCode: 'en',
        }),
        { chatCtx: initialContext },
      );
      agent.start(ctx.room, participant);

      await agent.say('Hi! I am Monica from Mosaic Investments. How can I help you today?', true);
    } catch (error) {
      console.error('Error occurred during agent entry/execution:', error);
      throw error;
    }
  },
});

cli.runApp(
  new WorkerOptions({ agent: fileURLToPath(import.meta.url), port: Number(process.env.PORT) }),
);
