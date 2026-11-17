"""Configuration & env loading for the Evals Caller Server."""

import os

from dotenv import load_dotenv

load_dotenv(override=False)

# macOS / python.org Python ships without a usable CA bundle, which makes outbound
# TLS to Deepgram/Cartesia fail with CERTIFICATE_VERIFY_FAILED. Point OpenSSL at
# certifi's bundle so the default SSL context can verify certs.
try:
    import certifi

    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("SSL_CERT_DIR", os.path.dirname(certifi.where()))
except ImportError:
    pass


# === Vobiz telephony ===
VOBIZ_AUTH_ID = os.getenv("VOBIZ_AUTH_ID", "")
VOBIZ_AUTH_TOKEN = os.getenv("VOBIZ_AUTH_TOKEN", "")
VOBIZ_API_BASE = os.getenv("VOBIZ_API_BASE", "https://api.vobiz.ai/api/v1")
# The evals agent's own number — used as the outbound caller ID (`from`).
VOBIZ_CALLER_ID = os.getenv("VOBIZ_CALLER_ID", "")

# === Provider API keys (evals agent's own STT/LLM/TTS) ===
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
CARTESIA_API_KEY = os.getenv("CARTESIA_API_KEY", "")

# === Public URLs (ngrok) for Vobiz callbacks ===
# e.g. https://<id>.ngrok.io  and  wss://<id>.ngrok.io
PUBLIC_HTTPS_URL = os.getenv("PUBLIC_HTTPS_URL", "").rstrip("/")
PUBLIC_WSS_URL = os.getenv("PUBLIC_WSS_URL", "").rstrip("/")

# === Audio / call settings ===
# Bundled audio assets (noise + barge-in sound clips).
_ASSETS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")

# JWT (must match evalra_backend for per-user library auth).
JWT_SECRET = os.getenv("JWT_SECRET", "evalra-default-secret-change-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

# 8000 -> μ-law, 16000 -> L16 (raw PCM). The serializer supports both.
SAMPLE_RATE = int(os.getenv("SAMPLE_RATE", "8000"))
SESSION_TIMEOUT_MINUTES = int(os.getenv("SESSION_TIMEOUT_MINUTES", "3"))
# Capture a WAV of the call. Toggle off (RECORD_CALLS=false) to isolate the recorder
# when diagnosing pipeline issues.
RECORD_CALLS = os.getenv("RECORD_CALLS", "true").strip().lower() in ("1", "true", "yes")
# Safety net: if no new transcript line lands from EITHER side for this long, the call has
# stalled (e.g. the agent keeps deferring without answering) — end it gracefully instead of
# riding it out until the agent hangs up or the session cap fires.
IDLE_TIMEOUT_SECS = float(os.getenv("IDLE_TIMEOUT_SECS", "45"))

# === Simulation defaults (overridable per call via the request's `simulations`) ===
# Fake barge-in: a loud noise burst over the agent while the TESTER stays silent — the agent
# should ignore it (a real barge-in is the tester actually talking over the agent).
FAKE_BARGE_IN_BURST_SECS = float(os.getenv("FAKE_BARGE_IN_BURST_SECS", "2.0"))

# === Turn-taking ===
# How long after Voicera's last word we wait before treating its turn as complete.
# Higher = fewer fragmented turns (so the tester replies once per Voicera turn instead
# of talking over itself), at the cost of a bit more latency.
USER_AGGREGATION_TIMEOUT = float(os.getenv("USER_AGGREGATION_TIMEOUT", "1.0"))
# Silence (seconds) before VAD considers the far end to have stopped speaking.
VAD_STOP_SECS = float(os.getenv("VAD_STOP_SECS", "0.3"))

# === Interruption-test scenario ===
# When enabled, the tester deliberately barges in: if Voicera is still speaking this
# many seconds into its turn, the tester talks over it to test barge-in handling.
INTERRUPT_AFTER_SECS = float(os.getenv("INTERRUPT_AFTER_SECS", "2.0"))
MAX_INTERRUPTIONS = int(os.getenv("MAX_INTERRUPTIONS", "1"))  # cap per call (don't derail/repeat)
INTERRUPT_LINE = os.getenv(
    "INTERRUPT_LINE", "Sorry to jump in — can I ask you something real quick?"
)
# Barge-in style: "speech" (spoken line), "sound" (loud noise clip), or "both".
BARGE_IN_STYLE = os.getenv("BARGE_IN_STYLE", "speech")
# Loud disruptive sound clips (assets/interruptions/) for sound/both barge-in styles.
_INTERRUPTIONS_DIR = os.path.join(_ASSETS, "interruptions")
_INTERRUPTION_LABEL_OVERRIDES = {
    "dogbarking": "Dog barking",
    "trucksounds": "Trucks",
    "farm": "Farm",
    "construction": "Construction",
}


def _interruption_key_from_stem(stem: str) -> str:
    s = stem.strip().lower()
    if s.endswith("_interruption"):
        s = s[: -len("_interruption")]
    return s


def _discover_interruption_files() -> tuple[dict[str, str], dict[str, str]]:
    files: dict[str, str] = {}
    labels: dict[str, str] = {}
    if not os.path.isdir(_INTERRUPTIONS_DIR):
        return files, labels
    for name in sorted(os.listdir(_INTERRUPTIONS_DIR)):
        lower = name.lower()
        if not lower.endswith(".mp3") or " copy" in lower:
            continue
        key = _interruption_key_from_stem(os.path.splitext(name)[0])
        if not key or key in files:
            continue
        files[key] = os.path.join(_INTERRUPTIONS_DIR, name)
        labels[key] = _INTERRUPTION_LABEL_OVERRIDES.get(key, key.replace("_", " ").title())
    return files, labels


INTERRUPTION_FILES, INTERRUPTION_LABELS = _discover_interruption_files()
DEFAULT_BARGE_IN_SOUND = (
    "trucksounds"
    if "trucksounds" in INTERRUPTION_FILES
    else (next(iter(INTERRUPTION_FILES), "trucksounds"))
)
BARGE_IN_SOUND_FILE = INTERRUPTION_FILES.get(
    DEFAULT_BARGE_IN_SOUND,
    os.path.join(_INTERRUPTIONS_DIR, "trucksounds.mp3"),
)
BARGE_IN_SOUND_SECS = float(os.getenv("BARGE_IN_SOUND_SECS", "3.0"))
DEFAULT_BARGE_IN_SOUND_VOLUME = float(os.getenv("DEFAULT_BARGE_IN_SOUND_VOLUME", "0.8"))
INTERRUPTION_PREVIEW_SECS = 5
# Spoken after a sound-only barge-in so the conversation recovers (and lands in context).
BARGE_IN_RECOVERY_LINE = os.getenv(
    "BARGE_IN_RECOVERY_LINE", "Sorry about that — it's a bit noisy here. Where were we?"
)

# Caller reaction clips (cough/hmm) played on outbound audio while the agent is speaking.
CALLER_FILLER_FILES = {
    "cough": os.path.join(_ASSETS, "cough.mp3"),
    "hmm": os.path.join(_ASSETS, "hmm.mp3"),
}
CALLER_FILLER_LABELS = {
    "cough": "Cough",
    "hmm": "Hmm",
}
CALLER_FILLER_INITIAL_DELAY_SECS = float(os.getenv("CALLER_FILLER_INITIAL_DELAY_SECS", "1.0"))
CALLER_FILLER_MIN_INTERVAL_SECS = float(os.getenv("CALLER_FILLER_MIN_INTERVAL_SECS", "2.0"))
CALLER_FILLER_MAX_INTERVAL_SECS = float(os.getenv("CALLER_FILLER_MAX_INTERVAL_SECS", "5.0"))
CALLER_FILLER_VOLUME = float(os.getenv("CALLER_FILLER_VOLUME", "0.5"))

# === Model selection ===
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
DEEPGRAM_MODEL = os.getenv("DEEPGRAM_MODEL", "nova-2")
DEEPGRAM_LANGUAGE = os.getenv("DEEPGRAM_LANGUAGE", "en-IN")
CARTESIA_MODEL = os.getenv("CARTESIA_MODEL", "sonic-2")
CARTESIA_VOICE_ID = os.getenv(
    "CARTESIA_VOICE_ID", "794f9389-aac1-45b6-b726-9d9369183238"
)

# === Language ===
# "en" -> Deepgram STT + Cartesia TTS (current). "mr" -> Google STT + Google TTS (Marathi).
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "en")
LANGUAGE_NAMES = {
    "en": "English", "hi": "Hindi", "ta": "Tamil", "te": "Telugu",
    "kn": "Kannada", "ml": "Malayalam", "bn": "Bengali", "gu": "Gujarati",
    "mr": "Marathi", "ur": "Urdu",
}
# Google service-account JSON (enabled for both Text-to-Speech and Speech-to-Text).
GOOGLE_CREDENTIALS_PATH = os.getenv(
    "GOOGLE_CREDENTIALS_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "tts_gcp.json"),
)
MARATHI_VOICE = os.getenv("MARATHI_VOICE", "mr-IN-Wavenet-B")


# Default test objective when the request doesn't specify one.
TEST_OBJECTIVE = os.getenv(
    "TEST_OBJECTIVE",
    "Find out the current status of your recent order and when it will be delivered.",
)

# Post-call LLM judge evaluation modes (stored in report meta.evaluation_mode).
EVAL_MODE_INTENT = "intent_understanding"
EVAL_MODE_FACTUAL = "factual_answer"
DEFAULT_EVALUATION_MODE = EVAL_MODE_INTENT

# Spoken opener queued the moment the call connects (the tester speaks first to break
# the mutual-silence deadlock — Voicera waits for the caller rather than greeting).
# Per-language so the opener and barge-in lines are spoken in the call's language.
OPENING_LINES = {
    "en": "Hello there, I was hoping you could help me with something.",
    "mr": "नमस्कार, मला तुमची एक गोष्टीत मदत हवी आहे.",
    "hi": "नमस्ते, मुझे एक बात में आपकी मदद चाहिए थी।",
    "kn": "ನಮಸ್ಕಾರ, ನನಗೆ ಒಂದು ವಿಷಯದಲ್ಲಿ ನಿಮ್ಮ ಸಹಾಯ ಬೇಕಿತ್ತು.",
    "ta": "வணக்கம், எனக்கு ஒரு விஷயத்தில் உங்கள் உதவி வேண்டும்.",
    "te": "నమస్కారం, నాకు ఒక విషయంలో మీ సహాయం కావాలి.",
    "gu": "નમસ્તે, મને એક બાબતમાં તમારી મદદ જોઈતી હતી.",
    "bn": "নমস্কার, আমার একটা বিষয়ে আপনার সাহায্য দরকার।",
}
INTERRUPT_LINES = {
    "en": "Sorry to jump in — can I ask you something real quick?",
    "mr": "माफ करा, मला पटकन काहीतरी विचारायचंय—",
}
RECOVERY_LINES = {
    "en": "Sorry about that — it's a bit noisy here. Where were we?",
    "mr": "माफ करा, इथे थोडा गोंगाट आहे. आपण कुठे होतो?",
}
# Speech-probe barge-in style: scripted stop/start commands + filler negative tests.
SPEECH_PROBE_STOP_LINES = {"en": "stop stop", "mr": "stop stop"}
SPEECH_PROBE_START_LINES = {"en": "start start", "mr": "start start"}
SPEECH_PROBE_FILLERS = ["hmm hmm", "ho ho", "ha ha"]
SPEECH_PROBE_COUGH_SOUND = "coughsound"
SPEECH_PROBE_FILLER_INITIAL_DELAY_SECS = float(
    os.getenv("SPEECH_PROBE_FILLER_INITIAL_DELAY_SECS", "0.25")
)
SPEECH_PROBE_FILLER_INTERVAL_SECS = float(os.getenv("SPEECH_PROBE_FILLER_INTERVAL_SECS", "0.35"))
SPEECH_PROBE_COMPLETION_TIMEOUT_SECS = float(
    os.getenv("SPEECH_PROBE_COMPLETION_TIMEOUT_SECS", "12.0")
)


def opening_line(lang: str) -> str:
    return OPENING_LINES.get(lang, OPENING_LINES["en"])


def interrupt_line(lang: str) -> str:
    return INTERRUPT_LINES.get(lang, INTERRUPT_LINES["en"])


def recovery_line(lang: str) -> str:
    return RECOVERY_LINES.get(lang, RECOVERY_LINES["en"])


def probe_stop_line(lang: str) -> str:
    return SPEECH_PROBE_STOP_LINES.get(lang, SPEECH_PROBE_STOP_LINES["en"])


def probe_start_line(lang: str) -> str:
    return SPEECH_PROBE_START_LINES.get(lang, SPEECH_PROBE_START_LINES["en"])


def resolve_interruption_file(
    sound_type: str | None,
    library_paths: dict[str, str] | None = None,
) -> str:
    """Path to a barge-in clip in assets/interruptions/, or empty if missing."""
    key = (sound_type or DEFAULT_BARGE_IN_SOUND).strip().lower()
    if library_paths and key in library_paths:
        path = library_paths[key]
        if path and os.path.isfile(path):
            return path
    path = INTERRUPTION_FILES.get(key)
    if path and os.path.isfile(path):
        return path
    if os.path.isfile(BARGE_IN_SOUND_FILE):
        return BARGE_IN_SOUND_FILE
    return ""


def resolve_noise_file(
    preset: str,
    library_paths: dict[str, str] | None = None,
) -> str | None:
    """Path to an ambient noise clip, or None if missing."""
    key = (preset or "off").strip().lower()
    if key == "off":
        return None
    if library_paths and key in library_paths:
        path = library_paths[key]
        if path and os.path.isfile(path):
            return path
    path = NOISE_FILES.get(key)
    if path and os.path.isfile(path):
        return path
    return None


def build_tester_prompt(
    objective: str, persona: str | None = None, language: str = "en"
) -> str:
    """Goal-directed, bounded tester prompt so two AI agents don't loop forever."""
    persona_line = (
        f"You are playing this caller: {persona}.\n" if persona else ""
    )
    lang_line = ""
    if language != "en":
        name = LANGUAGE_NAMES.get(language, language)
        lang_line = (
            f"IMPORTANT: Speak ONLY in {name} for the entire call — every word you say must "
            f"be in {name}. This includes your farewell when calling end_call.\n"
        )
    return (
        "OUTPUT FORMAT — READ THIS FIRST:\n"
        "Every single response you produce is ONE sentence only. One sentence. "
        "Write it, then stop immediately. Never write two sentences. Never write a question "
        "followed by another question. If you catch yourself writing a second sentence, delete it. "
        "One sentence per turn, always.\n\n"
        "You are an automated QA tester placing a phone call to a customer-service voice "
        "agent to test it. You are the CALLER/customer — never the agent. Never offer help "
        "or ask 'how can I help you'; you are the one who needs something.\n"
        f"{persona_line}{lang_line}\n"
        f"Your single goal for this call: {objective}\n\n"
        "WHEN TO END THE CALL — this is the most important rule:\n"
        "You must stay on the call and keep asking until you receive the SPECIFIC CONCRETE "
        "ANSWER your goal requires. Ask yourself: 'Did I actually get the specific fact I "
        "came for (a price, a date, an order status, a number)?' If the answer is no, you "
        "have NOT achieved your goal — keep the call going.\n\n"
        "These are NOT valid reasons to end:\n"
        "- The agent greeted you or introduced itself.\n"
        "- The agent said something vague like 'I can help with that' or 'let me check'.\n"
        "- The agent talked about related topics without answering your specific question.\n"
        "- You have been waiting — patience is required; do not hang up just because time passed.\n\n"
        "Valid reasons to end the call:\n"
        "   a) GOAL MET: You received the specific concrete answer your goal requires "
        "(e.g. a price was stated, a delivery date was given, a status was confirmed). "
        "The answer must be specific — 'we have information about that' is NOT specific.\n"
        "   b) HARD REFUSAL: The agent explicitly said it cannot help with your exact request "
        "(not just that it also handles other topics). 'I can help with X and Y' is NOT a refusal.\n"
        "   c) STUCK: The agent has deferred ('please wait', 'one moment', 'let me check') "
        "five or more times in a row without ever giving a real answer.\n\n"
        "How to run the call:\n"
        "1. You speak first with a brief greeting and your question in ONE sentence.\n"
        "2. If the agent gives a vague or incomplete reply, ask a follow-up that pushes for "
        "the specific fact — e.g. 'But what is the actual price?' or 'Can you give me the number?'\n"
        "3. Keep following up, one sentence at a time, until you get the concrete answer or hit "
        "a valid end condition above.\n"
        "4. To finish, call the `end_call` function with a short one-sentence farewell.\n\n"
        "Remember: ONE sentence per turn. Never reveal you are an automated tester."
    )


# === Background noise presets (mixed into the tester's OUTGOING audio) ===
NOISE_FILES = {
    "cafe": os.path.join(_ASSETS, "cafe_noise.mp3"),
    "factory": os.path.join(_ASSETS, "factory_noise.mp3"),
    "animal": os.path.join(_ASSETS, "animal_sound.mp3"),
    "tractor": os.path.join(_ASSETS, "tractor_sound.mp3"),
    "trucks": os.path.join(_ASSETS, "trucksounds.mp3"),
}
NOISE_LABELS = {
    "cafe": "Café",
    "factory": "Factory",
    "animal": "Animal",
    "tractor": "Tractor",
    "trucks": "Trucks",
}
NOISE_PREVIEW_SECS = 5
NOISE_PREPARE_RMS = float(os.getenv("NOISE_PREPARE_RMS", "0.10"))
NOISE_VOLUME = float(os.getenv("NOISE_VOLUME", "0.30"))
# Gain applied to the tester's TTS before noise is added, so the voice always sits
# above the background. 2.0 = ~6 dB boost. Tune via env if needed.
NOISE_TTS_GAIN = float(os.getenv("NOISE_TTS_GAIN", "2.0"))


# === LLM-judge metrics (Cekura-style), evaluated post-call from the transcript ===
# key -> (Cekura category, human label, expected result shape for the judge)
LLM_JUDGE_METRICS = {
    "expected_outcome": ("Accuracy", "Expected outcome", "one of: pass | review_required | failed"),
    "relevancy": ("Accuracy", "Relevancy", "true or false"),
    "response_consistency": ("Accuracy", "Response consistency", "true or false"),
    "unnecessary_repetition": ("Conversation Quality", "Unnecessary repetition", "integer count"),
    "verbosity": ("Conversation Quality", "Verbosity", "integer 1-5 (5 = concise)"),
    "appropriate_termination": ("Conversation Quality", "Appropriate termination", "true or false"),
    "sentiment": ("Customer Experience", "Sentiment", "one of: positive | neutral | negative"),
    "csat": ("Customer Experience", "CSAT", "integer 0-100"),
    "topic": ("Customer Experience", "Topic of call", "a short topic label"),
    "language_switch_handling": (
        "Accuracy",
        "Language switch handling",
        "one of: pass | review_required | failed",
    ),
}

EVAL_PRESETS = {
    "basic": [],  # deterministic metrics only
    "standard": ["expected_outcome"],
    "full": list(LLM_JUDGE_METRICS.keys()),
}


def resolve_evals(value) -> list[str]:
    """Resolve the request's `evals` (preset string or explicit list) to metric keys."""
    if value is None:
        value = "standard"
    if isinstance(value, str):
        return list(EVAL_PRESETS.get(value.strip().lower(), EVAL_PRESETS["standard"]))
    if isinstance(value, (list, tuple)):
        return [k for k in value if k in LLM_JUDGE_METRICS]
    return list(EVAL_PRESETS["standard"])


def is_baseline_call(run_config: dict) -> bool:
    """True when the call is a normal factual benchmark (no stress simulations).

    Baseline calls are used for the fleet-level E2E latency bucket so barge-in,
    ambient noise, language-switch, and legacy interruption tests do not skew
    conversational response-time percentiles.
    """
    sims = normalize_simulations(run_config.get("simulations"))
    if sims["ambient_noise"]["enabled"]:
        return False
    if sims["barge_in"]["enabled"]:
        return False
    if sims["language_switch"]["enabled"]:
        return False
    if run_config.get("test_interruptions"):
        return False
    noise = (run_config.get("background_noise") or "off").strip().lower()
    return noise in ("", "off")


def normalize_simulations(sims) -> dict:
    """Fill a per-call `simulations` dict from the UI with defaults so the rest of the
    code can read a stable shape. Every block has an `enabled` flag; disabled blocks are
    inert. This is the contract the frontend's Simulations panel writes to."""
    sims = sims or {}

    def block(name):
        b = sims.get(name) or {}
        return b if isinstance(b, dict) else {}

    noise = block("ambient_noise")
    barge = block("barge_in")
    lang = block("language_switch")

    return {
        "ambient_noise": {
            "enabled": bool(noise.get("enabled")),
            "type": (noise.get("type") or "cafe"),
            "volume": float(noise.get("volume", NOISE_VOLUME)),
        },
        "barge_in": {
            "enabled": bool(barge.get("enabled")),
            "real_count": int(barge.get("real_count", MAX_INTERRUPTIONS)),
            "after_secs": float(barge.get("after_secs", INTERRUPT_AFTER_SECS)),
            "style": (barge.get("style") or BARGE_IN_STYLE),
            "sound_type": (barge.get("sound_type") or DEFAULT_BARGE_IN_SOUND),
            "sound_volume": float(barge.get("sound_volume", DEFAULT_BARGE_IN_SOUND_VOLUME)),
            "fake_count": int(barge.get("fake_count", 0)),
            "fake_burst_secs": float(barge.get("fake_burst_secs", FAKE_BARGE_IN_BURST_SECS)),
            "fake_volume": float(barge.get("fake_volume", 0.8)),
            "cough_enabled": bool(barge.get("cough_enabled")),
            "hmm_enabled": bool(barge.get("hmm_enabled")),
            "filler_volume": float(barge.get("filler_volume", CALLER_FILLER_VOLUME)),
            "probe_stop_enabled": bool(barge.get("probe_stop_enabled", True)),
            "probe_start_enabled": bool(barge.get("probe_start_enabled", True)),
            "enabled_custom_reactions": [
                str(r).strip().lower()
                for r in (barge.get("enabled_custom_reactions") or [])
                if str(r).strip().lower().startswith("lib_")
            ],
        },
        "language_switch": {
            "enabled": bool(lang.get("enabled")),
            # `sequence` is the preferred form: a list of {after_turn, switch_to} steps
            # with cumulative after_turn counts. Falls back to the legacy single-switch fields.
            "sequence": (
                lang.get("sequence")
                or (
                    [{"after_turn": int(lang.get("after_turn", 1)), "switch_to": lang.get("switch_to") or "en"}]
                    if lang.get("switch_to")
                    else []
                )
            ),
            # Legacy single-switch fields kept for backward compat with old callers.
            "switch_to": (lang.get("switch_to") or "en"),
            "after_turn": int(lang.get("after_turn", 1)),
        },
    }
