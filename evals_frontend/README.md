# Evals Frontend

Minimal Next.js UI for `evals_caller_server`: fill a form (Voicera number, objective,
background noise, evals preset), trigger the call, and watch the report render natively
(React components) once the call finishes.

## Run

```bash
cd evals_frontend
npm install
cp .env.example .env.local   # already created; point NEXT_PUBLIC_EVALS_API at the backend
npm run dev                  # http://localhost:3000
```

The backend (`evals_caller_server`) must be running on the URL in `.env.local`
(default `http://localhost:7870`), with ngrok up so Vobiz can reach it.

## How it works

1. The form POSTs to `POST /api/evals-call` and gets back a `call_id`.
2. It polls `GET /api/report/{call_id}/status` every 4s.
3. When `ready`, it fetches `GET /api/report/{call_id}` (structured JSON) and renders it
   natively with `app/Report.tsx`.
