"""GCP-based mid-call language switching for the evals tester agent.

The tester agent gets a `switch_language` tool. When it calls this tool:
  - GoogleSTTService.set_language() restarts the gRPC stream with the new language
  - GoogleHttpTTSService._settings["language"] + voice_id are updated in place (HTTP, stateless)

The LanguageSwitchController can also trigger a direct switch (bypassing the tool) when
the time-based simulation fires — the system message it injects tells the LLM to speak
in the new language, and the STT/TTS are already switched.
"""

from __future__ import annotations

import json

from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.transcriptions.language import Language

# ISO code → (BCP-47 language code for TTS, Google WaveNet voice, pipecat Language enum)
GCP_LANGUAGE_MAP: dict[str, tuple[str, str, Language]] = {
    "en": ("en-IN", "en-IN-Wavenet-A", Language.EN_IN),
    "hi": ("hi-IN", "hi-IN-Wavenet-C", Language.HI_IN),
    "ta": ("ta-IN", "ta-IN-Wavenet-A", Language.TA_IN),
    "te": ("te-IN", "te-IN-Wavenet-A", Language.TE_IN),
    "kn": ("kn-IN", "kn-IN-Wavenet-A", Language.KN_IN),
    "ml": ("ml-IN", "ml-IN-Wavenet-A", Language.ML_IN),
    "bn": ("bn-IN", "bn-IN-Wavenet-A", Language.BN_IN),
    "gu": ("gu-IN", "gu-IN-Wavenet-A", Language.GU_IN),
    "mr": ("mr-IN", "mr-IN-Wavenet-B", Language.MR_IN),
    "ur": ("ur-IN", "ur-IN-Wavenet-A", Language.UR_IN),
}

# Reverse map: pipecat Language enum → ISO code (used for log messages)
GCP_LANGUAGE_MAP_REVERSE: dict = {}  # populated after GCP_LANGUAGE_MAP is defined

LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "ml": "Malayalam",
    "bn": "Bengali",
    "gu": "Gujarati",
    "mr": "Marathi",
    "ur": "Urdu",
}

# "I only know X, please speak X." in each supported language — used by the
# LanguageSwitchController to inject the exact scripted phrase via TTS (bypasses
# LLM generation so the wrong script is never chosen).
LANG_ONLY_PHRASES: dict[str, str] = {
    "en": "I only know English, please speak in English.",
    "hi": "मुझे केवल हिंदी आती है, कृपया हिंदी में बात करें।",
    "kn": "ನನಗೆ ಕೇವಲ ಕನ್ನಡ ಗೊತ್ತು, ದಯವಿಟ್ಟು ಕನ್ನಡದಲ್ಲಿ ಮಾತನಾಡಿ.",
    "mr": "मला फक्त मराठी येते, कृपया मराठीत बोला.",
    "te": "నాకు తెలుగు మాత్రమే తెలుసు, దయచేసి తెలుగులో మాట్లాడండి.",
    "ta": "எனக்கு தமிழ் மட்டுமே தெரியும், தமிழில் பேசுங்கள்.",
    "ml": "എനിക്ക് മലയാളം മാത്രമേ അറിയൂ, ദയവായി മലയാളത്തിൽ സംസാരിക്കൂ.",
    "bn": "আমি শুধু বাংলা জানি, দয়া করে বাংলায় কথা বলুন।",
    "gu": "મને ફક્ત ગુજરાતી આવડે છે, ગુજરાતીમાં વાત કરો.",
    "ur": "مجھے صرف اردو آتی ہے، براہ کرم اردو میں بات کریں۔",
}

GCP_LANGUAGE_MAP_REVERSE.update({v[2]: k for k, v in GCP_LANGUAGE_MAP.items()})

LANGUAGE_SWITCH_TOOL_PROMPT = (
    "\n\n## Language switching\n"
    "You have a `switch_language` tool. Use it ONLY when the agent explicitly and clearly "
    "asks you to speak in a different language "
    '(e.g. "please speak in Hindi", "Hindi mein baat karein").\n'
    "When you receive a system message directing you to switch language, the switch is already "
    "done for you — do NOT call `switch_language`. Just speak in the new language as instructed.\n"
    "Do NOT switch just because the agent uses a few words of another language or mixes languages. "
    "Only switch on a clear, deliberate agent request. Supported codes: "
    + ", ".join(f"{k} ({v})" for k, v in LANGUAGE_NAMES.items())
    + "."
)


def create_switch_language_tool_schema() -> FunctionSchema:
    return FunctionSchema(
        name="switch_language",
        description=(
            "Switch the tester's speaking (TTS) and listening (STT) language mid-call. "
            "Call this before speaking in a new language. "
            "Supported codes: " + ", ".join(sorted(GCP_LANGUAGE_MAP))
        ),
        properties={
            "language": {
                "type": "string",
                "description": (
                    "ISO language code, e.g. hi for Hindi, ta for Tamil, mr for Marathi."
                ),
                "enum": sorted(GCP_LANGUAGE_MAP),
            }
        },
        required=["language"],
    )


async def apply_gcp_language_switch(stt, tts, code: str, agent_lang: str | None = None) -> bool:
    """Switch both STT and TTS to `code`. Returns True on success.

    TTS: updated synchronously (GoogleHttpTTSService is stateless per-request HTTP).
    STT: gRPC stream reconnect is launched as a background task so this function returns
    immediately. Waiting for the reconnect inline blocked _inject for 90+ seconds because
    the gRPC stream waits for pending state to drain before restarting.

    agent_lang: ISO code of the language Voicera responds in (e.g. "kn"). Kept in the
    STT language list so Voicera's responses are still transcribed after the switch.
    """
    mapping = GCP_LANGUAGE_MAP.get(code)
    if not mapping:
        return False
    bcp47, voice, lang_enum = mapping
    # TTS first: instant update, tester speaks in new language on next LLM turn.
    tts._settings["language"] = bcp47
    tts.set_voice(voice)
    logger.info(f"🌐 TTS switched to {LANGUAGE_NAMES.get(code, code)} ({bcp47}, {voice})")
    # STT: background reconnect so _inject doesn't block.
    import asyncio as _asyncio
    from pipecat.transcriptions.language import Language as _Language

    # Build STT language list (max 3 for GCP STT v2):
    #   1. tester's new language (primary — what we speak)
    #   2. Voicera agent's language (what we listen to), if different
    #   3. English fallback
    agent_mapping = GCP_LANGUAGE_MAP.get(agent_lang or "")
    agent_enum = agent_mapping[2] if agent_mapping else None

    seen: list = [lang_enum]
    if agent_enum and agent_enum != lang_enum:
        seen.append(agent_enum)
    if _Language.EN_IN not in seen:
        seen.append(_Language.EN_IN)
    langs = seen[:3]

    async def _reconnect():
        try:
            await stt.set_languages(langs)
            names = [LANGUAGE_NAMES.get(GCP_LANGUAGE_MAP_REVERSE.get(l, ""), l) for l in langs]
            logger.info(f"🌐 STT reconnected: {' + '.join(str(n) for n in names)}")
        except Exception as e:
            logger.error(f"🌐 STT reconnect failed for {code}: {e}")

    _asyncio.create_task(_reconnect())
    return True


def register_switch_language_tool(
    llm, stt, tts, current_lang: list[str], metrics=None
) -> None:
    """Register the switch_language function on the LLM service.

    current_lang is a one-element list used as a mutable reference to the active ISO code.
    metrics (optional MetricsCollector) records the lang_switch event when a tool-triggered
    switch fires (so the ledger count is accurate even for reactive switches).
    """

    async def _handler(params):
        raw = (params.arguments or {}).get("language", "")
        code = str(raw).strip().lower()

        if code not in GCP_LANGUAGE_MAP:
            await params.result_callback(json.dumps({
                "success": False,
                "error": f"Unsupported language code: {raw!r}",
                "supported": sorted(GCP_LANGUAGE_MAP),
            }))
            return

        if code == current_lang[0]:
            await params.result_callback(
                json.dumps({"success": True, "language": code, "unchanged": True})
            )
            return

        ok = await apply_gcp_language_switch(stt, tts, code)
        if ok:
            current_lang[0] = code
            if metrics is not None:
                metrics.record_event("lang_switch", "agent_should_adapt")
            await params.result_callback(json.dumps({"success": True, "language": code}))
        else:
            await params.result_callback(json.dumps({
                "success": False,
                "error": "Internal error during language switch",
            }))

    llm.register_function("switch_language", _handler, cancel_on_interruption=False)
