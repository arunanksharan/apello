AI Interviewer

Have a conversation about any article on the web
studypal is a fast conversational AI built using Daily for real-time media transport and Cartesia for text-to-speech. Everything is orchestrated together (VAD -> STT -> LLM -> TTS) using Pipecat.

Setup
Clone the repository
Copy env.example to a .env file and add API keys
Install the required packages: pip install -r requirements.txt
Run python3 studypal.py from your command line.
While the app is running, go to the https://<yourdomain>.daily.co/<room_url> set in DAILY_SAMPLE_ROOM_URL and talk to studypal!
