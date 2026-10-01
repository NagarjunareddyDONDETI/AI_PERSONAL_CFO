# Finzo voice

Finzo has two voice entry points. Both end in the same place: `main.voice_ask`,
which runs follow-up resolution, retrieval, memory, intent routing and
`agents/copilot.converse` exactly as typed chat does.

| | Push-to-talk (dashboard) | Hands-free service |
|---|---|---|
| Starts listening | You hold the Finzo voice button | You say "Hey Finzo" |
| Runs in | The browser + API server | Its own background process |
| Needs the dashboard open | Yes | No |
| Speech-to-text | `STT_PROVIDER` chain, Voicebox first | faster-whisper, then Voicebox |
| Speech output | `TTS_PROVIDER` chain, Voicebox first | Voicebox, then Windows SAPI |

## 1. Architecture

```
microphone
  ├─ dashboard: hold button ─ POST /finzo/voice/chat ─┐
  └─ service:   VAD ─ tiny.en wake probe ─ Whisper ───┤
                                                      ▼
                 main.voice_ask  (the existing CFO pipeline, unchanged)
                   session.resolve  ->  retriever  ->  memory recall
                   ->  route_intent  ->  _relevant_slice(stored analysis)
                   ->  converse(): the LLM may only narrate figures it is given
                                                      ▼
                 speech.for_speech  (markdown off, "₹4,820" -> "4,820 rupees")
                                                      ▼
                 TTS registry: Voicebox -> fallbacks  ->  speaker
```

Voicebox is isolated in `backend/voice/voicebox/`. Nothing else knows its URLs
or payloads; the rest of the app sees two more providers in the existing
registries (`voice/stt/voicebox.py`, `voice/tts/voicebox.py`). Swapping TTS
engines later is an `.env` change.

**Where the numbers come from.** Every figure spoken is taken from the stored
analysis (`database.get_result`), sliced for the question's intent, and injected
into the prompt as "the source of truth for all numbers". With no LLM configured
Finzo returns the computed data itself. Voicebox is always called with
`personality: false`, because its persona mode runs its own LLM over the text and
could reword a figure.

Files:

```
backend/voice/voicebox/         client.py (HTTP), config.py (VOICEBOX_*)
backend/voice/stt/voicebox.py   STT provider
backend/voice/stt/faster_whisper_local.py   local STT, CUDA->CPU fallback
backend/voice/tts/voicebox.py   TTS provider
backend/voice/handsfree/        the hands-free service
backend/voice/main.py           python -m voice.main
start_finzo_voice.bat / stop_finzo_voice.bat
frontend/src/services/finzoVoice.ts        recording + playback
frontend/src/components/FinzoVoiceButton.tsx, VoiceVisualizer.tsx
```

API (all require login):

| Route | Purpose |
|---|---|
| `POST /finzo/voice/chat` | form `file` (audio) or `transcript`, `speak` → answer + `audio_b64`, `audio_mime`, `tts_provider` |
| `GET /finzo/voice/health` | Voicebox reachability, active STT/TTS providers, hands-free state |
| `GET /voice/handsfree/status` | hands-free state; transcript only for the account it serves |
| `POST /voice/handsfree/stop` | ask the service to exit (its own account only) |

There is deliberately no `/start`: a process that opens the microphone should be
started by the person at the machine, not by an HTTP request.

## 2. Installation

From the repository root:

```powershell
cd backend
.venv\Scripts\pip install -r requirements.txt
cd ..\frontend
npm install
```

## 3. Dependencies added

| Package | Why |
|---|---|
| `faster-whisper==1.1.1` | local Whisper on CTranslate2; no torch |
| `sounddevice==0.5.1` | microphone capture and playback (bundles PortAudio) |
| `webrtcvad-wheels==2.0.14` | voice activity detection; binary wheels, no compiler |
| `pyttsx3==2.98` | offline Windows SAPI voice when Voicebox is closed |
| `vitest@2.1.9` (frontend, dev) | frontend tests |

All have Python 3.13 Windows wheels. None pulls torch.

## 4. Voicebox setup

1. Download the Windows installer from https://voicebox.sh and run it.
2. Open Voicebox once. Its API starts on `http://127.0.0.1:17493`.
   Check it: `curl http://127.0.0.1:17493/health` should report `"status": "healthy"`.
3. Create the Finzo voice profile (next section).
4. In `backend/.env`:
   ```
   VOICEBOX_ENABLED=true
   VOICEBOX_BASE_URL=http://127.0.0.1:17493
   VOICEBOX_VOICE_ID=Finzo
   ```
5. Restart the backend. `GET /finzo/voice/health` should show `voicebox.ok: true`
   and `voicebox` first in `tts_providers`.

Interactive API docs for your installed version: `http://127.0.0.1:17493/docs`.

### Creating the Finzo voice profile

In the Voicebox app, create a new voice profile named **Finzo**. Either:

- **Preset voice (quickest):** choose a preset from the Kokoro or Qwen
  CustomVoice engines. Pick a calm male English voice.
- **Cloned voice:** record or upload 10–30 seconds of clean speech in the
  delivery you want (calm, measured, friendly) with its exact transcript.

Then set `VOICEBOX_VOICE_ID` to the profile name (`Finzo`) or its id. Confirm
the name Finzo will match:

```powershell
curl http://127.0.0.1:17493/profiles
```

Optional tuning: `VOICEBOX_ENGINE` forces an engine; `VOICEBOX_INSTRUCT` gives a
delivery hint, which only Qwen engines honour.

## 5. Whisper setup

Models download automatically from Hugging Face on first use and are cached in
`%USERPROFILE%\.cache\huggingface`. The service uses two:

- `tiny.en` (~75 MB) to spot the wake phrase. Cheap enough to run on every utterance.
- `WHISPER_MODEL` (default `small`, ~480 MB) for the actual question.

Pre-download them so the first "Hey Finzo" is not slow:

```powershell
cd backend
.venv\Scripts\python -m voice.main --selftest
```

## 6. Microphone setup

```powershell
.venv\Scripts\python -m voice.main --list-devices
```

The starred device is the Windows default. To use another, set `MIC_DEVICE` to
its index or part of its name. If Windows blocks access: Settings → Privacy &
security → Microphone → allow desktop apps.

In the dashboard, the browser asks for permission the first time you hold the
button. It only works on `http://localhost:5173` or HTTPS.

## 7. Wake word

```
WAKE_WORD_ENABLED=true
WAKE_WORD=hey finzo
```

"Hey Finzo", "Okay Finzo" and a bare "Finzo" all activate. You can ask in one
breath ("Hey Finzo, how much did I spend on food this month?") or wait for
"Yes?". After an answer you have `FOLLOWUP_SECONDS` (default 6) to ask a
follow-up without the wake word.

False activations are kept down by the rules already used in the browser path:
a deny list (finance, financial, fine, …), a match only within the first three
words, and at most one character of mishearing.

Only a VAD-gated utterance is ever decoded, and audio never leaves the machine
for wake detection.

## 8. TTS setup

- Dashboard: `TTS_PROVIDER=voicebox,gtts,edge_tts`. Voicebox is skipped while
  closed. gTTS and Edge are cloud services: remove them from the list if answer
  text must never leave the machine.
- Service: `FINZO_DAEMON_TTS=voicebox,pyttsx3`, local-only by default.
  `PYTTSX3_VOICE=David` selects the stock male Windows voice;
  `PYTTSX3_RATE=172` is a calm, moderate pace.

## 9. GPU configuration

`WHISPER_DEVICE=auto` tries CUDA, then falls back to CPU. On an RTX 2050 (4 GB),
`small` with `int8` uses around 0.5 GB of VRAM.

CTranslate2 needs NVIDIA's **cuBLAS for CUDA 12** and **cuDNN 9** DLLs on
`PATH`. Without them the log says `cublas64_12.dll is not found` and Finzo uses
the CPU. To enable the GPU, install the CUDA 12 toolkit and cuDNN 9 (or the
`nvidia-cublas-cu12` and `nvidia-cudnn-cu12` pip wheels and add their `bin`
folders to `PATH`), then run `--selftest`: the `gpu` line should show a device.
*This step was not verified on the development machine, which lacks the DLLs.*

## 10. CPU fallback

Automatic, and it never crashes the app:

- CUDA is only accepted after a real warm-up inference succeeds, because a model
  can load onto the GPU and only fail when first used.
- A CUDA failure marks CUDA unusable for the rest of the process. Retrying it was
  observed to hang rather than fail when cuBLAS is missing.
- An out-of-memory error mid-transcription reloads the model on the CPU and
  retries that same clip.

Force CPU with `WHISPER_DEVICE=cpu`. On CPU, `small` transcribes a short question
in 1–3 s; `WHISPER_MODEL=base` is faster and less accurate.

## 11. Running

Backend and dashboard (two terminals):

```powershell
cd backend;  .venv\Scripts\python -m uvicorn main:app --host 127.0.0.1 --port 8000
cd frontend; npm run dev
```

Hands-free service. Set `FINZO_VOICE_USER_EMAIL` in `backend/.env` to your login
email first, since it decides whose finances Finzo answers about.

```powershell
start_finzo_voice.bat      # background, no console, no admin rights
stop_finzo_voice.bat
```

Foreground, for watching what it does:

```powershell
cd backend
.venv\Scripts\python -m voice.main
```

It loads the pipeline in-process, so it works with the dashboard closed and even
with the API server stopped. To start it at login, put a shortcut to
`start_finzo_voice.bat` in `shell:startup`.

## 12. Testing

```powershell
cd backend;  .venv\Scripts\python -m pytest tests/test_voicebox_client.py tests/test_finzo_voice_chat.py tests/test_handsfree.py
cd frontend; npm test
```

`test_finzo_voice_chat.py::test_e2e_spoken_food_question` covers audio →
Voicebox STT → intent → stored data → answer → Voicebox TTS → playable WAV, with
Voicebox mocked at the HTTP layer. `test_handsfree.py::test_real_audio_wake_word_and_question`
synthesizes the question with Windows SAPI and runs it through the real VAD and
both Whisper models.

**Voice input.** Hold the button, ask "How much did I spend on food this
month?", release. The transcript appears under "You:". For the service, run it
in the foreground with `VOICE_DEBUG=true` to log what the wake detector heard.

**Voice output.** `--selftest` renders a test sentence with your TTS chain.
Replay any clip without a microphone:

```powershell
.venv\Scripts\python -m voice.main --simulate question.wav --save-speech out
```

This feeds a 16 kHz WAV in place of the microphone, prints each question and
answer, and writes every spoken answer to `out\`.

## 13. Troubleshooting

| Symptom | Check |
|---|---|
| Dashboard says "Voicebox offline" | Is the Voicebox app open? `curl http://127.0.0.1:17493/health` |
| "No Voicebox profile matches" | `curl …/profiles`; `VOICEBOX_VOICE_ID` must equal a name or id |
| "Voicebox is downloading its Whisper model" | First transcription in Voicebox; wait and retry |
| Voicebox slow on first answer | It loads the TTS model on first use; later answers are faster |
| `cublas64_12.dll is not found` | Expected without CUDA libraries; running on CPU (section 9) |
| Service will not start | `backend\.finzo\voice.log`, then `--selftest` |
| "Set FINZO_VOICE_USER_EMAIL" | More than one account exists; choose yours |
| Finzo does not hear "Hey Finzo" | `VOICE_DEBUG=true`, run in the foreground, read the "heard" lines; try `VAD_AGGRESSIVENESS=1` or another `MIC_DEVICE` |
| Finzo interrupts itself | Use headphones, or lower speaker volume; there is no acoustic echo cancellation |
| Answers come back slowly | Check the backend log for LLM 429s (free-tier rate limits) |

Voicebox connection debugging: `GET /finzo/voice/health` returns the exact error
and latency. Health is cached for `VOICEBOX_HEALTH_TTL` seconds, so the first
request after starting Voicebox may still use the fallback voice.

## 14. Performance tuning

- Wake detection decodes only the first `WAKE_PROBE_SECONDS` (2.5) of each utterance with `tiny.en`.
- `SILENCE_TIMEOUT` (1.2 s) decides when you have finished. Lower is snappier and cuts off slow speakers.
- Models load once and stay resident; nothing reinitialises per question.
- Audio captured while Finzo is thinking is discarded, not queued.
- `WHISPER_MODEL=base` roughly halves CPU transcription time.

## 15. Security and privacy

- Microphone audio is never written to disk and never sent to an LLM. Idle
  listening is decoded locally, and only VAD-detected speech is.
- Voicebox is expected on loopback. A non-local `VOICEBOX_BASE_URL` logs a
  warning, because answers containing balances would cross the network.
- Logs record lengths, providers and timings, not transcripts or figures.
  `VOICE_DEBUG=true` is the exception and should stay off.
- `backend/.finzo/` (status, log) is git-ignored. The status file holds the last
  question and answer for the dashboard and is removed when the service stops.
- Finzo reports figures. It does not move money, and nothing in the voice path
  can initiate a payment, transfer or investment.

## 16. Limitations and future work

- **Voicebox end-to-end was verified against mocks only.** The routes and
  payloads come from Voicebox's source, but it was not installed on the
  development machine.
- The hands-free service uses the system speaker with no echo cancellation. A
  loud answer can be picked up by the microphone; it is ignored unless it
  contains the wake word or a stop phrase.
- The no-LLM fallback for spending questions reads out raw computed data. It is
  correct but not conversational.
- Derived percentages come from the LLM, which can round loosely even when every
  base figure is exact. Pre-computing month-over-month deltas and shares in the
  analysis would remove that.
- A dedicated keyword spotter (openWakeWord, Porcupine) would cut idle CPU
  further. It only needs to implement `WakeDetector`.
- Streaming Voicebox output sentence by sentence would start speech sooner.
