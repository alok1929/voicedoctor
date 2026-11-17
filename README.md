# Evals Caller Server (POC)

A standalone AI-calls-AI POC. One FastAPI endpoint dials a **Voicera** number through
**Vobiz** and runs a Pipecat pipeline (Deepgram STT → OpenAI LLM → Cartesia TTS) that acts
as a QA tester, holding a real phone conversation with the live Voicera agent.

Voicera is treated as a pure black box — we just call the number. Nothing in Voicera is touched.

## Flow

```
POST /api/evals-call { voicera_number }
  -> Vobiz /Call/  (from=VOBIZ_CALLER_ID, to=voicera_number, answer_url=/answer?call_id=...)
  -> Vobiz dials Voicera (prod); Voicera answers + greets
  -> Vobiz POSTs /answer  -> returns Stream XML -> wss /agent/{call_id}
  -> WS /agent/{call_id}: tester pipeline talks to Voicera; transcript logged to console
```

The tester listens first (no greeting), runs with interruptions disabled, and ends on a
3-minute timeout or when Voicera hangs up.

## Setup

```bash
cd evals_caller_server
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in creds (already done locally)
```

## Run

```bash
# 1) start the server
python main.py                       # listens on :7870

# 2) expose it publicly
ngrok http 7870
#    set PUBLIC_HTTPS_URL=https://<id>.ngrok.io and PUBLIC_WSS_URL=wss://<id>.ngrok.io
#    in .env, then restart the server

# 3) trigger a call
curl -X POST http://localhost:7870/api/evals-call \
  -H 'Content-Type: application/json' \
  -d '{"voicera_number":"+91XXXXXXXXXX"}'
```

Watch the server logs: `/answer` hit → WS connected → `start` frame → Voicera greets → tester
responds; each turn is logged as `📝 user: ...` (Voicera) / `📝 assistant: ...` (tester).

## Notes

- `SAMPLE_RATE=8000` (μ-law) by default; set `16000` (L16) if audio quality needs it.
- ngrok URL changes on each restart unless you use a reserved domain — update `.env` accordingly.
- Latency stacks across both legs; multi-second gaps between turns are expected for a POC.
