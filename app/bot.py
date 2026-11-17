"""Minimal Pipecat pipeline for the evals (QA tester) agent.

Stripped-down sibling of voice_2_voice_server/api/bot.py: no MinIO, no metrics,
no greeting/idle filters, no backend integrations. STT -> LLM -> TTS, with the
tester persona as the system prompt, talking to the live Voicera agent over Vobiz.
"""

import asyncio
import os
import random
import time
import wave

from loguru import logger

from deepgram import LiveOptions
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    LLMRunFrame,
    OutputAudioRawFrame,
    StartFrame,
    TTSSpeakFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_response import LLMUserAggregatorParams
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor
from pipecat.processors.transcript_processor import TranscriptProcessor
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transcriptions.language import Language
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from app import config
from app import metrics as M
from app.language_switching import (
    GCP_LANGUAGE_MAP,
    LANG_ONLY_PHRASES,
    LANGUAGE_NAMES,
    LANGUAGE_SWITCH_TOOL_PROMPT,
    apply_gcp_language_switch,
    create_switch_language_tool_schema,
    register_switch_language_tool,
)
from app.metrics import MetricsCollector, install_bot_frame_diagnostics, log_bot_frame_diagnostics
from app.report import RECORDINGS_DIR, build_report
from serializer.vobiz_serializer import VobizFrameSerializer


def _create_stt(language: str):
    """Marathi -> Google STT; otherwise Deepgram."""
    if language == "mr":
        from pipecat.services.google.stt import GoogleSTTService
        from pipecat.transcriptions.language import Language

        return _stt_ignoring_self_audio(GoogleSTTService)(
            credentials_path=config.GOOGLE_CREDENTIALS_PATH,
            sample_rate=config.SAMPLE_RATE,
            params=GoogleSTTService.InputParams(
                languages=[Language.MR_IN],
                # The Marathi recognizer doesn't support these features (causes 400s).
                enable_automatic_punctuation=False,
                enable_spoken_punctuation=False,
                enable_spoken_emojis=False,
            ),
        )
    return _stt_ignoring_self_audio(DeepgramSTTService)(
        api_key=config.DEEPGRAM_API_KEY,
        sample_rate=config.SAMPLE_RATE,
        live_options=LiveOptions(
            model=config.DEEPGRAM_MODEL,
            language=config.DEEPGRAM_LANGUAGE,
            channels=1,
            encoding="linear16",
            sample_rate=config.SAMPLE_RATE,
            interim_results=True,
            endpointing=150,
            smart_format=True,
            punctuate=True,
        ),
    )


def _create_llm() -> OpenAILLMService:
    return OpenAILLMService(
        api_key=config.OPENAI_API_KEY,
        model=config.OPENAI_MODEL,
    )


def _create_google_stt(initial_language: str, agent_language: str | None = None):
    """Google STT V2 for language-switching mode.

    language_codes priority (GCP supports up to 3):
      1. tester's language (what we speak)
      2. Voicera agent's response language (what we listen to) — if different from tester
      3. en-IN as universal fallback

    This ensures Voicera's responses get transcribed even when the agent speaks a
    different language than the tester (e.g. tester=Marathi, agent=Kannada).
    """
    from pipecat.services.google.stt import GoogleSTTService

    tester_mapping = GCP_LANGUAGE_MAP.get(initial_language)
    tester_enum = tester_mapping[2] if tester_mapping else Language.EN_IN

    agent_mapping = GCP_LANGUAGE_MAP.get(agent_language or "")
    agent_enum = agent_mapping[2] if agent_mapping else None

    seen: list = [tester_enum]
    if agent_enum and agent_enum != tester_enum:
        seen.append(agent_enum)
    if Language.EN_IN not in seen:
        seen.append(Language.EN_IN)
    lang_list = seen[:3]  # GCP STT v2 max 3 language codes

    logger.info(f"🌐 STT languages: {[str(l) for l in lang_list]}")
    return _stt_ignoring_self_audio(GoogleSTTService)(
        credentials_path=config.GOOGLE_CREDENTIALS_PATH,
        sample_rate=config.SAMPLE_RATE,
        params=GoogleSTTService.InputParams(
            languages=lang_list,
            enable_automatic_punctuation=False,
            enable_spoken_punctuation=False,
            enable_spoken_emojis=False,
        ),
    )


def _create_google_http_tts(initial_language: str):
    """Google HTTP TTS for language-switching mode. Uses WaveNet voices per language."""
    from pipecat.services.google.tts import GoogleHttpTTSService
    from pipecat.transcriptions.language import Language

    mapping = GCP_LANGUAGE_MAP.get(initial_language)
    if mapping:
        bcp47, voice, lang_enum = mapping
    else:
        bcp47, voice, lang_enum = ("en-IN", "en-IN-Wavenet-A", Language.EN_IN)
    return GoogleHttpTTSService(
        credentials_path=config.GOOGLE_CREDENTIALS_PATH,
        voice_id=voice,
        sample_rate=config.SAMPLE_RATE,
        params=GoogleHttpTTSService.InputParams(language=lang_enum),
    )


def _create_tts(language: str):
    """Marathi -> Google TTS (mr-IN voice); otherwise Cartesia."""
    if language == "mr":
        # NOTE: GoogleTTSService uses the streaming synthesis API, which Google now
        # restricts to Chirp 3 HD voices ("400 Currently, only Chirp 3: HD voices are
        # supported for streaming synthesis."). Our Marathi voice is a Wavenet voice,
        # so we use the HTTP (non-streaming) service, which supports all voice types.
        from pipecat.services.google.tts import GoogleHttpTTSService
        from pipecat.transcriptions.language import Language

        return GoogleHttpTTSService(
            credentials_path=config.GOOGLE_CREDENTIALS_PATH,
            voice_id=config.MARATHI_VOICE,
            sample_rate=config.SAMPLE_RATE,
            params=GoogleHttpTTSService.InputParams(language=Language.MR_IN),
        )
    return CartesiaTTSService(
        api_key=config.CARTESIA_API_KEY,
        model=config.CARTESIA_MODEL,
        voice_id=config.CARTESIA_VOICE_ID,
        encoding="pcm_s16le",
    )


def _prepare_noise_file(preset: str, src_path: str, target_sr: int) -> str:
    """Downmix to mono, resample to target_sr, and peak-normalize — cached as WAV.

    SoundfileMixer does NOT resample (silently skips mismatched files), so we
    pre-render a rate-matched file. Peak-normalising to full scale ensures the
    `volume` parameter (0.0–1.0) is the actual fraction of loudness heard by
    the caller: without normalisation the raw MP3 amplitude can be so low that
    even volume=0.9 produces an inaudible result.
    """
    import numpy as np
    import soundfile as sf
    import soxr

    cache_dir = os.path.join(os.path.dirname(src_path), ".cache")
    os.makedirs(cache_dir, exist_ok=True)
    # Cache key includes prepare RMS so retuning loudness invalidates old hot files.
    rms_tag = int(config.NOISE_PREPARE_RMS * 100)
    dst = os.path.join(cache_dir, f"{preset}_{target_sr}_rms{rms_tag}.wav")
    if os.path.exists(dst):
        return dst

    data, sr = sf.read(src_path, dtype="int16")
    if data.ndim == 2:  # stereo -> mono
        data = data.mean(axis=1).astype("int16")
    flo = data.astype("float32") / 32768.0
    if sr != target_sr:
        flo = soxr.resample(flo, sr, target_sr)
    # RMS-normalize to a modest level so the UI volume slider (0.1–1.0) maps to
    # perceptually useful background levels. The old 0.5 target made even 35% loud.
    rms = np.sqrt(np.mean(flo ** 2))
    target_rms = config.NOISE_PREPARE_RMS
    if rms > 0:
        flo = flo * (target_rms / rms)
    flo = np.clip(flo, -1.0, 1.0)
    data = (np.clip(flo, -1.0, 1.0) * 32767).astype("int16")
    sf.write(dst, data, target_sr, subtype="PCM_16")
    return dst


def _load_barge_in_sound(
    target_sr: int,
    max_secs: float,
    sound_type: str | None = None,
    library_paths: dict[str, str] | None = None,
) -> bytes:
    """Mono, target_sr, first `max_secs` of the barge-in sound clip as raw PCM16 bytes."""
    import numpy as np
    import soundfile as sf
    import soxr

    src = config.resolve_interruption_file(sound_type, library_paths=library_paths)
    if not src:
        logger.warning(f"Barge-in sound file missing for type={sound_type!r}")
        return b""
    data, sr = sf.read(src, dtype="int16")
    if data.ndim == 2:  # stereo -> mono
        data = data.mean(axis=1).astype("int16")
    if sr != target_sr:
        flo = data.astype("float32") / 32768.0
        flo = soxr.resample(flo, sr, target_sr)
        data = (np.clip(flo, -1.0, 1.0) * 32767).astype("int16")
    data = data[: int(target_sr * max_secs)]  # clip to a few seconds
    return data.tobytes()


def _load_caller_filler_sound(src_path: str, target_sr: int) -> bytes:
    """Mono, target_sr, full caller-reaction clip (cough/hmm) as raw PCM16 bytes."""
    import numpy as np
    import soundfile as sf
    import soxr

    if not src_path or not os.path.exists(src_path):
        logger.warning(f"Caller filler sound file missing: {src_path}")
        return b""
    data, sr = sf.read(src_path, dtype="int16")
    if data.ndim == 2:
        data = data.mean(axis=1).astype("int16")
    if sr != target_sr:
        flo = data.astype("float32") / 32768.0
        flo = soxr.resample(flo, sr, target_sr)
        data = (np.clip(flo, -1.0, 1.0) * 32767).astype(np.int16)
    return data.tobytes()


def _scale_pcm16_bytes(raw: bytes, volume: float) -> bytes:
    """Scale int16 PCM by volume in 0.0–1.0."""
    import numpy as np

    if not raw:
        return raw
    vol = max(0.0, min(1.0, float(volume)))
    if vol == 1.0:
        return raw
    arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) * vol
    return np.clip(arr, -32768, 32767).astype(np.int16).tobytes()


class CallerFillerSoundsController(FrameProcessor):
    """Play cough/hmm clips on the outbound leg while the agent under test is speaking."""

    def __init__(
        self,
        clips: dict[str, bytes],
        sample_rate: int,
        volume: float,
        metrics=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._clips = clips
        self._sample_rate = sample_rate
        self._volume = volume
        self.metrics = metrics
        self.task = None
        self._user_speaking = False
        self._loop_task: asyncio.Task | None = None

    async def _stop_loop(self) -> None:
        if self._loop_task is None:
            return
        self._loop_task.cancel()
        try:
            await self._loop_task
        except asyncio.CancelledError:
            pass
        self._loop_task = None

    async def _play_clip(self, kind: str, pcm: bytes) -> None:
        inject_t = time.monotonic()
        logger.info(f"🎭 Caller filler: playing {kind!r}")
        if self.metrics:
            if kind == "cough":
                event = M.EV_FILLER_COUGH
            elif kind == "hmm":
                event = M.EV_CALLER_HMM
            else:
                event = M.EV_CALLER_HMM
            self.metrics.record_event(event, "agent_should_ignore", t=inject_t)
        frame = OutputAudioRawFrame(
            audio=_scale_pcm16_bytes(pcm, self._volume),
            sample_rate=self._sample_rate,
            num_channels=1,
        )
        if self.task is not None:
            await self.task.queue_frames([frame])
        else:
            await self.push_frame(frame)

    async def _filler_loop(self) -> None:
        try:
            await asyncio.sleep(config.CALLER_FILLER_INITIAL_DELAY_SECS)
            while self._user_speaking:
                kind = random.choice(list(self._clips.keys()))
                await self._play_clip(kind, self._clips[kind])
                if not self._user_speaking:
                    break
                delay = random.uniform(
                    config.CALLER_FILLER_MIN_INTERVAL_SECS,
                    config.CALLER_FILLER_MAX_INTERVAL_SECS,
                )
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            pass
        finally:
            self._loop_task = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, UserStartedSpeakingFrame):
            self._user_speaking = True
            if self._loop_task is None or self._loop_task.done():
                self._loop_task = asyncio.create_task(self._filler_loop())
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._user_speaking = False
        elif isinstance(frame, (EndFrame, CancelFrame)):
            self._user_speaking = False
            await self._stop_loop()
        await self.push_frame(frame, direction)


def _build_caller_filler_controller(
    sims: dict,
    sample_rate: int,
    metrics=None,
    library_paths: dict[str, str] | None = None,
) -> CallerFillerSoundsController | None:
    """Return a caller-filler processor when cough/hmm or custom reactions are enabled."""
    barge = sims["barge_in"]
    if not barge["enabled"]:
        return None
    custom_ids = barge.get("enabled_custom_reactions") or []
    if not (barge.get("cough_enabled") or barge.get("hmm_enabled") or custom_ids):
        return None

    clips: dict[str, bytes] = {}
    if barge.get("cough_enabled"):
        pcm = _load_caller_filler_sound(config.CALLER_FILLER_FILES["cough"], sample_rate)
        if pcm:
            clips["cough"] = pcm
    if barge.get("hmm_enabled"):
        pcm = _load_caller_filler_sound(config.CALLER_FILLER_FILES["hmm"], sample_rate)
        if pcm:
            clips["hmm"] = pcm
    paths = library_paths or {}
    for rid in custom_ids:
        src = paths.get(rid)
        if not src:
            continue
        pcm = _load_caller_filler_sound(src, sample_rate)
        if pcm:
            clips[rid] = pcm
    if not clips:
        logger.error("Caller filler sounds enabled but no clips could be loaded")
        return None

    vol = max(0.0, min(1.0, float(barge.get("filler_volume", config.CALLER_FILLER_VOLUME))))
    enabled = ", ".join(clips.keys())
    logger.info(f"🎭 Caller filler sounds enabled ({enabled}) @ {vol:.0%}")
    return CallerFillerSoundsController(
        clips=clips,
        sample_rate=sample_rate,
        volume=vol,
        metrics=metrics,
    )


class BargeInController(FrameProcessor):
    """Interruption-test scenario: deliberately talk over Voicera to test barge-in.

    Watches Voicera's VAD turns; if it is still speaking `after_secs` into a turn, the
    tester speaks an interruption line over it (capped per call). The line is also added
    to the LLM context so the tester recovers coherently afterwards. The deterministic
    metrics (tester_interrupts_voicera, voicera_stop_after_interruption) capture the result.
    """

    def __init__(
        self,
        style: str,
        line: str,
        recovery_line: str,
        after_secs: float,
        max_count: int,
        sample_rate: int,
        fake_count: int = 0,
        fake_burst_secs: float = 2.0,
        sound_type: str | None = None,
        sound_volume: float = 0.8,
        fake_volume: float = 0.8,
        metrics=None,
        library_paths: dict[str, str] | None = None,
    ):
        super().__init__()
        self.style = style  # "speech" | "sound" | "both"
        self.line = line
        self.recovery_line = recovery_line
        self.after_secs = after_secs
        self.max_count = max_count      # real barge-ins
        self.fake_count = fake_count    # fake/noise bursts (agent should ignore)
        self.sample_rate = sample_rate
        self.sound_volume = sound_volume
        self.fake_volume = fake_volume
        self.metrics = metrics          # MetricsCollector, for ground-truth events
        # A sound clip is needed for sound/both styles AND for any fake bursts.
        need_sound = style in ("sound", "both") or fake_count > 0
        clip_secs = max(config.BARGE_IN_SOUND_SECS, fake_burst_secs)
        self._sound = (
            _load_barge_in_sound(
                sample_rate, clip_secs, sound_type, library_paths=library_paths
            )
            if need_sound
            else b""
        )
        self.task = None       # set after PipelineTask is created
        self.context = None    # set after the OpenAILLMContext is created
        self._user_speaking = False
        self._armed = False
        self._real = 0
        self._fake = 0
        self._pending_llm_run = False  # fire LLMRunFrame on next Voicera-stops event

    def _remaining(self):
        return (self._real < self.max_count) or (self._fake < self.fake_count)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, UserStartedSpeakingFrame):
            self._user_speaking = True
            if not self._armed and self._remaining() and self.task is not None:
                self._armed = True
                asyncio.create_task(self._maybe_barge_in())
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._user_speaking = False
            self._armed = False
            if self._pending_llm_run and self.task is not None:
                self._pending_llm_run = False
                await self.task.queue_frames([LLMRunFrame()])
        await self.push_frame(frame, direction)

    async def _maybe_barge_in(self):
        await asyncio.sleep(self.after_secs)
        # Only barge in if Voicera is *still* talking and we have something left to do.
        if not (self._user_speaking and self._remaining() and self.task is not None):
            return
        # Real barge-ins first (the tester asserts its question), then fake/noise probes.
        if self._real < self.max_count:
            await self._do_real()
        elif self._fake < self.fake_count:
            await self._do_fake()

    async def _do_real(self):
        self._real += 1
        inject_t = time.monotonic()
        logger.info(f"🗣️➡️ Real barge-in #{self._real} (style={self.style})")
        if self.metrics:
            self.metrics.record_event(
                "real_bargein",
                "agent_should_stop",
                t=inject_t,
                meta={
                    "configured_after_secs": self.after_secs,
                    "barge_in_index": self._real,
                },
            )
            self.metrics.mark_tester_interrupt(inject_t)
        frames = []
        if self.style in ("sound", "both") and self._sound:
            frames.append(
                OutputAudioRawFrame(
                    audio=_scale_pcm16_bytes(self._sound, self.sound_volume),
                    sample_rate=self.sample_rate,
                    num_channels=1,
                )
            )
        spoken = self.recovery_line if self.style == "sound" else self.line
        if spoken:
            if self.context is not None:
                self.context.add_message({"role": "assistant", "content": spoken})
            frames.append(TTSSpeakFrame(spoken))
        await self.task.queue_frames(frames)
        # Defer the follow-up LLM turn until Voicera stops speaking.  Firing LLMRunFrame
        # immediately causes its TTS output to be cancelled by the pipeline's own barge-in
        # suppression (UserStartedSpeakingFrame resets TTS while Voicera is still talking).
        self._pending_llm_run = True

    async def _do_fake(self):
        self._fake += 1
        inject_t = time.monotonic()
        logger.info(f"🔊🚫 Fake barge-in #{self._fake} (noise burst; agent should ignore)")
        if self.metrics:
            self.metrics.record_event("fake_noise", "agent_should_ignore", t=inject_t)
        # A loud burst over the agent with NO spoken line and NO LLM turn: the tester stays
        # silent, so a well-behaved agent should keep talking (not treat noise as a barge-in).
        if self._sound:
            await self.task.queue_frames(
                [
                    OutputAudioRawFrame(
                        audio=_scale_pcm16_bytes(self._sound, self.fake_volume),
                        sample_rate=self.sample_rate,
                        num_channels=1,
                    )
                ]
            )


class SpeechProbeController(FrameProcessor):
    """Scripted speech-probe simulation: stop/start commands + filler negative tests.

    Turn detection uses finalized transcript lines (not raw VAD fragments) so GCP
    streaming STT mid-utterance UserStarted/Stopped frames do not derail the sequence.
    """

    def __init__(
        self,
        language: str,
        after_secs: float,
        sample_rate: int,
        sound_volume: float,
        metrics=None,
        stop_enabled: bool = True,
        start_enabled: bool = True,
        caller_cough_enabled: bool = False,
    ):
        super().__init__()
        self.language = language
        self.after_secs = after_secs
        self.sample_rate = sample_rate
        self.sound_volume = sound_volume
        self.metrics = metrics
        self._stop_enabled = stop_enabled
        self._start_enabled = start_enabled
        self._caller_cough_enabled = caller_cough_enabled
        self.task = None
        self.context = None
        self._user_speaking = False
        self._tester_final_turns = 0
        self._agent_final_turns = 0
        self._stop_injected = False
        self._start_pending = False
        self._fillers_after_start = False
        self._fillers_running = False
        self._pending_task: asyncio.Task | None = None
        self._fillers_task: asyncio.Task | None = None
        self._probe_phrases = {
            config.probe_stop_line(language).strip().lower(),
            config.probe_start_line(language).strip().lower(),
            *(p.strip().lower() for p in config.SPEECH_PROBE_FILLERS),
        }
        self._cough_pcm = _load_barge_in_sound(
            sample_rate, config.BARGE_IN_SOUND_SECS, config.SPEECH_PROBE_COUGH_SOUND
        )
        if not self._cough_pcm:
            logger.warning(
                f"🎤 Speech probe: cough clip missing "
                f"(type={config.SPEECH_PROBE_COUGH_SOUND!r})"
            )

    def note_opener_played(self):
        """Opener is pre-injected at connect — counts as the first tester turn."""
        self._tester_final_turns = max(self._tester_final_turns, 1)

    def on_transcript(self, role: str, content: str):
        """Track finalized conversation turns from transcript updates."""
        text = (content or "").strip()
        if not text:
            return
        if role == "assistant":
            if text.lower() in self._probe_phrases:
                return
            self._tester_final_turns += 1
            logger.debug(
                f"🎤 Speech probe: tester turn {self._tester_final_turns} "
                f"(agent={self._agent_final_turns})"
            )
        elif role == "user":
            self._agent_final_turns += 1
            logger.debug(
                f"🎤 Speech probe: agent turn {self._agent_final_turns} "
                f"(tester={self._tester_final_turns})"
            )

    def _schedule_inject(self, probe: str):
        if self._pending_task and not self._pending_task.done():
            return
        logger.info(
            f"🎤 Speech probe arming {probe!r} in {self.after_secs}s "
            f"(tester_turns={self._tester_final_turns}, agent_turns={self._agent_final_turns})"
        )
        self._pending_task = asyncio.create_task(self._delayed_inject(probe))

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, UserStartedSpeakingFrame):
            self._user_speaking = True
            if self._fillers_after_start and not self._fillers_running:
                self._fillers_after_start = False
                self._start_fillers_and_cough()
            elif self._start_pending:
                self._start_pending = False
                if self._start_enabled:
                    self._schedule_inject("start")
            elif (
                self._stop_enabled
                and not self._stop_injected
                and self._agent_final_turns >= 1
                and self._tester_final_turns >= 2
            ):
                self._schedule_inject("stop")
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._user_speaking = False
            # Do not cancel pending injects — VAD emits many brief stop/start cycles
            # mid-utterance; BargeInController keeps its sleep task running for the same reason.
        await self.push_frame(frame, direction)

    async def _delayed_inject(self, probe: str):
        try:
            await asyncio.sleep(self.after_secs)
            if self.task is None:
                return
            if probe == "stop":
                if self._stop_injected:
                    return
                await self._inject_speech(
                    config.probe_stop_line(self.language),
                    M.EV_PROBE_STOP,
                    "agent_should_stop",
                )
                self._stop_injected = True
                if self._start_enabled:
                    self._start_pending = True
            elif probe == "start":
                if not self._start_enabled:
                    return
                await self._inject_speech(
                    config.probe_start_line(self.language),
                    M.EV_PROBE_START,
                    "agent_should_stop",
                )
                if self._user_speaking:
                    self._start_fillers_and_cough()
                else:
                    self._fillers_after_start = True
                    logger.info(
                        "🎤 Speech probe: agent quiet after start — "
                        "fillers/cough will run on next agent speech"
                    )
        except asyncio.CancelledError:
            pass
        finally:
            self._pending_task = None

    def _start_fillers_and_cough(self):
        if self._fillers_running or (
            self._fillers_task is not None and not self._fillers_task.done()
        ):
            return
        self._fillers_task = asyncio.create_task(self._run_fillers_and_cough())

    async def wait_for_probes_complete(self, timeout: float | None = None):
        """Wait for pending stop/start injects and filler/cough sequence."""
        timeout = timeout if timeout is not None else config.SPEECH_PROBE_COMPLETION_TIMEOUT_SECS
        tasks = [
            t
            for t in (self._pending_task, self._fillers_task)
            if t is not None and not t.done()
        ]
        if not tasks:
            return
        done, pending = await asyncio.wait(tasks, timeout=timeout)
        if pending:
            logger.warning(
                f"🎤 Speech probe: {len(pending)} task(s) still running after {timeout}s"
            )
        for task in done:
            if task.cancelled():
                continue
            exc = task.exception()
            if exc:
                logger.error(f"🎤 Speech probe task failed: {exc}")

    async def _inject_speech(self, line: str, kind: str, expected: str, meta=None):
        inject_t = time.monotonic()
        logger.info(f"🎤 Speech probe inject ({kind}): {line!r}")
        if self.metrics:
            payload_meta = {"configured_after_secs": self.after_secs, **(meta or {})}
            if kind == M.EV_FILLER_SPEECH:
                payload_meta["phrase"] = line
            self.metrics.record_event(kind, expected, t=inject_t, meta=payload_meta)
            if kind in (M.EV_PROBE_STOP, M.EV_PROBE_START):
                self.metrics.mark_tester_interrupt(inject_t)
        if self.context is not None:
            self.context.add_message({"role": "assistant", "content": line})
        await self.task.queue_frames([TTSSpeakFrame(line)])

    async def _run_fillers_and_cough(self):
        if self._fillers_running:
            return
        self._fillers_running = True
        try:
            initial = config.SPEECH_PROBE_FILLER_INITIAL_DELAY_SECS
            interval = config.SPEECH_PROBE_FILLER_INTERVAL_SECS
            for i, phrase in enumerate(config.SPEECH_PROBE_FILLERS):
                delay = initial if i == 0 else interval
                if delay > 0:
                    await asyncio.sleep(delay)
                if self.task is None:
                    return
                await self._inject_speech(
                    phrase, M.EV_FILLER_SPEECH, "agent_should_ignore", meta={"phrase": phrase}
                )
            if interval > 0:
                await asyncio.sleep(interval)
            if self._caller_cough_enabled:
                logger.info(
                    "🎤 Speech probe: skipping end cough — caller cough reactions are enabled"
                )
                return
            if self.task is None or not self._cough_pcm:
                logger.warning("🎤 Speech probe: cough clip missing or task gone")
                return
            inject_t = time.monotonic()
            logger.info("🎤 Speech probe inject (filler_cough): cough sound")
            if self.metrics:
                self.metrics.record_event(M.EV_FILLER_COUGH, "agent_should_ignore", t=inject_t)
            await self.task.queue_frames(
                [
                    OutputAudioRawFrame(
                        audio=_scale_pcm16_bytes(self._cough_pcm, self.sound_volume),
                        sample_rate=self.sample_rate,
                        num_channels=1,
                    )
                ]
            )
        except asyncio.CancelledError:
            pass
        finally:
            self._fillers_running = False


class LanguageSwitchController:
    """Sequence-aware mid-call language switch controller.

    Walks through a list of {after_turn, switch_to} steps (cumulative agent-turn counts).
    Each step fires after the tester's response to the N-th cumulative Voicera turn, then
    the next step waits for its own cumulative threshold.

    Timing: inject fires on the TESTER's transcript event AFTER the N-th agent turn so
    we don't race with the natural pipeline LLM run (which fires from context_aggregator.user()
    on the same agent-turn event). Injecting there caused double consecutive tester turns.

    The injected system message tells the tester to say "I only know {language}" on the
    very next turn, which naturally prompts Voicera to adapt.
    """

    def __init__(self, sequence: list[dict], metrics, context, task,
                 stt=None, tts=None, current_lang: list[str] | None = None,
                 agent_lang: str | None = None):
        # sequence: [{"after_turn": N, "switch_to": "xx"}, ...] sorted by after_turn
        self._sequence = sorted(sequence, key=lambda x: x["after_turn"])
        self._step = 0           # which step we're currently targeting
        self.metrics = metrics
        self.context = context
        self.task = task
        self.stt = stt
        self.tts = tts
        self.current_lang = current_lang
        self.agent_lang = agent_lang  # Voicera's response language — kept in STT list after switch
        self._agent_turns = 0
        self._pending_inject = False
        self._pending_code = None
        # Rate-limit: don't fire the next inject until the tester has responded to
        # the current one. Voicera sometimes sends two fragments in rapid succession
        # which would otherwise fire two injects before the LLM sees either.
        self._waiting_for_tester_response = False

    def _current_target(self):
        if self._step < len(self._sequence):
            return self._sequence[self._step]
        return None

    async def on_agent_turn(self):
        """Called from the async transcript handler; fires the inject synchronously
        (before context_aggregator.user() triggers the LLM) so the LLM's very next
        response already starts with the 'I only know X' phrase in the new language.

        Rate-limited: if we already injected and the tester hasn't responded yet,
        skip — Voicera often sends 2–3 transcript fragments before we generate one
        tester turn, and back-to-back injects confuse the LLM with contradictory instructions.
        """
        if self._waiting_for_tester_response:
            return
        target = self._current_target()
        if target is None:
            return
        self._agent_turns += 1
        if self._agent_turns >= target["after_turn"]:
            code = target["switch_to"]
            step_idx = self._step
            self._step += 1

            if self.current_lang is not None and self.current_lang[0] == code:
                logger.info(f"🌐 Already in {code}; skipping step {step_idx}")
                return
            self._waiting_for_tester_response = True
            await self._inject(code, step_idx)

    def on_tester_turn(self):
        """Called when the tester's transcript fires — clears the rate-limit gate."""
        self._waiting_for_tester_response = False

    async def _inject(self, code: str, step_idx: int):
        try:
            name = LANGUAGE_NAMES.get(code) or config.LANGUAGE_NAMES.get(code, code)
            phrase = LANG_ONLY_PHRASES.get(code, f"I only know {name}, please speak in {name}.")
            logger.info(f"🌐 Language switch step {step_idx}: tester → {name} ({code})")

            if self.stt is not None and self.tts is not None:
                ok = await apply_gcp_language_switch(self.stt, self.tts, code, agent_lang=self.agent_lang)
                if ok and self.current_lang is not None:
                    self.current_lang[0] = code

            # Tell the LLM to start its NEXT response with the exact native phrase.
            # "OVERRIDES all previous" so rapid successive injects don't confuse the LLM.
            self.context.add_message({"role": "system", "content": (
                f"[LANGUAGE SWITCH — OVERRIDES ALL PREVIOUS LANGUAGE INSTRUCTIONS] "
                f"Your current language is now {name}. "
                f"Your VERY NEXT response must be EXACTLY this single phrase and nothing else "
                f"(copy verbatim, no additions, no translation, no question after it): "
                f'"{phrase}" '
                f"That is your entire next response — one sentence, stop immediately after it. "
                f"From the turn after that, continue asking about your goal ONLY in {name} script. "
                f"Do NOT call switch_language."
            )})
            if self.metrics:
                self.metrics.record_event("lang_switch", "agent_should_adapt")
        except Exception as e:
            logger.error(f"🌐 _inject failed for step {step_idx} ({code}): {e}", exc_info=True)


def _stt_ignoring_self_audio(stt_cls):
    """Wrap an STT service so it forwards — but never transcribes — audio we inject.

    The interruption test queues a barge-in sound (an OutputAudioRawFrame) at the
    pipeline source via queue_frames; it travels downstream THROUGH the STT service on
    its way to the output transport. Base STTService transcribes any AudioRawFrame
    (OutputAudioRawFrame included), so without this guard it feeds our own sound clip to
    the recognizer. A 3s clip at 8kHz/16-bit is 48000 bytes, which trips Google streaming
    STT's 25600-byte chunk cap ("Audio chunk can be of a maximum of 25600 bytes.") and
    400s. Here we let only real mic audio (InputAudioRawFrame) reach the recognizer.
    """

    class _GuardedSTT(stt_cls):
        async def process_frame(self, frame: Frame, direction: FrameDirection):
            if isinstance(frame, OutputAudioRawFrame):
                await self.push_frame(frame, direction)
                return
            await super().process_frame(frame, direction)

    # Preserve the original name so logs and metrics keying (substring "sttservice")
    # still resolve to e.g. "GoogleSTTService#0".
    _GuardedSTT.__name__ = stt_cls.__name__
    _GuardedSTT.__qualname__ = stt_cls.__qualname__
    return _GuardedSTT


class AmbientNoiseProcessor(FrameProcessor):
    """Mix continuous background noise into outbound audio (speech + silence).

    Runs in the pipeline before AudioBufferProcessor so recordings match what
    Voicera hears. A background loop injects noise-only frames while the tester
    is silent; speech frames are mixed inline with TTS gain applied first.
    """

    def __init__(
        self,
        noise_data: bytes,
        noise_sr: int,
        volume: float,
        outbound_sr: int,
        tts_gain: float = 2.0,
        **kwargs,
    ):
        super().__init__(**kwargs)
        import numpy as np

        self._noise_raw = np.frombuffer(noise_data, dtype=np.int16).copy()
        self._noise_sr = noise_sr
        self._noise_at_outbound: "np.ndarray | None" = None
        self._volume = volume
        self._tts_gain = tts_gain
        self._outbound_sr = outbound_sr
        self._pos = 0
        self._tts_active = False
        self._running = False
        self._loop_task: asyncio.Task | None = None
        # Match Pipecat transport default: 4 × 10 ms chunks.
        self._chunk_samples = max(1, int(outbound_sr / 100) * 4)

    def _ensure_noise_at_outbound(self) -> None:
        import numpy as np
        import soxr

        if self._noise_at_outbound is not None:
            return
        if self._noise_sr == self._outbound_sr:
            self._noise_at_outbound = self._noise_raw
            return
        flo = self._noise_raw.astype("float32") / 32768.0
        flo = soxr.resample(flo, self._noise_sr, self._outbound_sr)
        self._noise_at_outbound = np.clip(flo * 32767, -32767, 32767).astype(np.int16)

    def _noise_chunk(self, n: int, sample_rate: int):
        import numpy as np
        import soxr

        self._ensure_noise_at_outbound()
        noise = self._noise_at_outbound
        if sample_rate != self._outbound_sr:
            flo = noise.astype("float32") / 32768.0
            flo = soxr.resample(flo, self._outbound_sr, sample_rate)
            noise = np.clip(flo * 32767, -32767, 32767).astype(np.int16)
        noise_len = len(noise)
        if noise_len == 0:
            return np.zeros(n, dtype=np.int16)
        indices = np.arange(self._pos, self._pos + n) % noise_len
        self._pos = (self._pos + n) % noise_len
        return (noise[indices].astype(np.int32) * self._volume).astype(np.int16)

    def _mix_speech(self, frame: OutputAudioRawFrame) -> OutputAudioRawFrame:
        import numpy as np

        audio = np.frombuffer(frame.audio, dtype=np.int16).astype(np.int32)
        n = len(audio)
        boosted = np.clip(audio * self._tts_gain, -32768, 32767)
        noise = self._noise_chunk(n, frame.sample_rate).astype(np.int32)
        mixed = np.clip(boosted + noise, -32768, 32767).astype(np.int16)
        # Preserve TTSAudioRawFrame so transport.output() can emit BotStarted/Stopped.
        frame_cls = type(frame)
        return frame_cls(
            audio=mixed.tobytes(),
            sample_rate=frame.sample_rate,
            num_channels=frame.num_channels,
        )

    def _start_loop(self) -> None:
        if self._loop_task is not None:
            return
        self._running = True
        self._loop_task = asyncio.create_task(self._noise_loop())

    async def _stop_loop(self) -> None:
        self._running = False
        if self._loop_task is None:
            return
        self._loop_task.cancel()
        try:
            await self._loop_task
        except asyncio.CancelledError:
            pass
        self._loop_task = None

    async def _noise_loop(self) -> None:
        interval = self._chunk_samples / self._outbound_sr
        while self._running:
            if not self._tts_active:
                chunk = self._noise_chunk(self._chunk_samples, self._outbound_sr)
                await self.push_frame(
                    OutputAudioRawFrame(
                        audio=chunk.tobytes(),
                        sample_rate=self._outbound_sr,
                        num_channels=1,
                    )
                )
            await asyncio.sleep(interval)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, StartFrame):
            self._outbound_sr = frame.audio_out_sample_rate or self._outbound_sr
            self._chunk_samples = max(1, int(self._outbound_sr / 100) * 4)
            self._noise_at_outbound = None
            self._start_loop()
        elif isinstance(frame, (EndFrame, CancelFrame)):
            await self._stop_loop()
        elif isinstance(frame, TTSStartedFrame):
            self._tts_active = True
        elif isinstance(frame, TTSStoppedFrame):
            self._tts_active = False
        elif isinstance(frame, OutputAudioRawFrame):
            frame = self._mix_speech(frame)
        await self.push_frame(frame, direction)


def _resolve_noise_volume(volume: float | None) -> float:
    """Clamp UI volume (0.1–1.0) to a usable mixing gain."""
    if volume is None:
        return config.NOISE_VOLUME
    return max(0.0, min(1.0, float(volume)))


def _build_ambient_noise_processor(
    background_noise: str,
    volume: float | None,
    outbound_sr: int,
    library_paths: dict[str, str] | None = None,
) -> AmbientNoiseProcessor | None:
    """Return a pipeline processor for continuous ambient noise, or None when off."""
    import soundfile as sf

    preset = (background_noise or "off").strip().lower()
    if preset == "off":
        return None
    src = config.resolve_noise_file(preset, library_paths=library_paths)
    if not src or not os.path.exists(src):
        return None
    vol = _resolve_noise_volume(volume)
    try:
        prepared = _prepare_noise_file(preset, src, outbound_sr)
        data, sr = sf.read(prepared, dtype="int16")
        logger.info(
            f"🎚️ Continuous background noise '{preset}' @ {vol:.0%} "
            f"(tts_gain={config.NOISE_TTS_GAIN}x) -> {prepared}"
        )
        return AmbientNoiseProcessor(
            noise_data=data.tobytes(),
            noise_sr=sr,
            volume=vol,
            outbound_sr=outbound_sr,
            tts_gain=config.NOISE_TTS_GAIN,
        )
    except Exception as e:
        logger.error(f"Failed to init ambient noise processor: {e}")
        return None


async def run_evals_bot(
    websocket_client, stream_sid: str, call_sid: str, run_config: dict | None = None
) -> None:
    """Set up the transport + pipeline and run the tester agent until the call ends."""
    run_config = run_config or {}
    library_paths = run_config.get("library_paths") or {}
    sample_rate = config.SAMPLE_RATE
    language = (run_config.get("language") or config.DEFAULT_LANGUAGE or "en").strip().lower()
    objective = run_config.get("objective") or config.TEST_OBJECTIVE
    persona = run_config.get("persona")
    max_minutes = run_config.get("max_duration_minutes") or config.SESSION_TIMEOUT_MINUTES
    session_timeout = max_minutes * 60
    # Structured simulation cases (UI-driven), with flat legacy flags as fallback.
    sims = config.normalize_simulations(run_config.get("simulations"))
    interruptions_on = sims["barge_in"]["enabled"] or bool(run_config.get("test_interruptions"))
    interrupt_after = sims["barge_in"]["after_secs"]
    barge_in_style = sims["barge_in"]["style"]
    barge_in_sound = sims["barge_in"]["sound_type"]
    speech_probes_on = sims["barge_in"]["enabled"] and barge_in_style == "speech_probes"
    # File the report (and recording) under the API-returned call_id, falling back to the
    # Vobiz call_sid. Computed up front so the recording handler can name the WAV.
    report_id = run_config.get("call_id") or call_sid
    recording_start = {"t": None}  # epoch secs when audio capture began (for transcript offsets)
    call_started_mono = {"t": None}  # monotonic secs at media connect (for transcript offsets)
    logger.info(f"🌐 Language: {language}")

    serializer = VobizFrameSerializer(
        stream_sid=stream_sid,
        call_sid=call_sid,
        params=VobizFrameSerializer.InputParams(
            vobiz_sample_rate=sample_rate,
            sample_rate=sample_rate,
        ),
    )

    vad_analyzer = SileroVADAnalyzer(
        sample_rate=sample_rate,
        params=VADParams(
            stop_secs=config.VAD_STOP_SECS,
            min_volume=0.4,
            confidence=0.3,
            start_secs=0.1,
        ),
    )

    # Ambient-noise simulation takes precedence; fall back to the legacy flat fields.
    if sims["ambient_noise"]["enabled"]:
        noise_preset = sims["ambient_noise"]["type"]
        noise_volume = sims["ambient_noise"]["volume"]
    else:
        noise_preset = run_config.get("background_noise", "off")
        noise_volume = run_config.get("noise_volume")
    ambient_noise_proc = _build_ambient_noise_processor(
        noise_preset, noise_volume, sample_rate, library_paths=library_paths
    )
    transport = FastAPIWebsocketTransport(
        websocket=websocket_client,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            vad_analyzer=vad_analyzer,
            serializer=serializer,
            audio_in_passthrough=True,
            session_timeout=session_timeout,
            audio_in_sample_rate=sample_rate,
            audio_out_sample_rate=sample_rate,
        ),
    )

    # Language-switching mode: use Google STT + Google HTTP TTS so set_language() works.
    # Activated when the language_switch simulation is enabled OR when a GCP-supported
    # language is explicitly set (anything other than the Deepgram/Cartesia defaults).
    lang_switch_sim_on = sims["language_switch"]["enabled"]
    use_gcp_stack = lang_switch_sim_on or (language in GCP_LANGUAGE_MAP and language != "en")

    if use_gcp_stack:
        agent_lang = run_config.get("voicera_response_language") or None
        stt = _create_google_stt(language, agent_language=agent_lang)
        tts = _create_google_http_tts(language)
        logger.info(f"🌐 Using GCP STT+TTS stack (language={language}, agent_lang={agent_lang}, lang_switch_sim={lang_switch_sim_on})")
    else:
        stt = _create_stt(language)
        tts = _create_tts(language)

    llm = _create_llm()

    # current_lang is a mutable one-element list shared between the tool handler and
    # LanguageSwitchController so both always see the current active language.
    current_lang: list[str] = [language]

    end_call_tool = FunctionSchema(
        name="end_call",
        description=(
            "Hang up the phone call. Call this once your question has been answered, or once "
            "the agent has made clear it cannot help. This is how you end the call."
        ),
        properties={
            "farewell": {
                "type": "string",
                "description": "A short goodbye line to speak before hanging up.",
            }
        },
        required=["farewell"],
    )

    if use_gcp_stack:
        tools = ToolsSchema(standard_tools=[end_call_tool, create_switch_language_tool_schema()])
    else:
        tools = ToolsSchema(standard_tools=[end_call_tool])

    system_prompt = config.build_tester_prompt(objective, persona, language)
    if use_gcp_stack:
        system_prompt += LANGUAGE_SWITCH_TOOL_PROMPT

    context = OpenAILLMContext(
        [{"role": "system", "content": system_prompt}],
        tools=tools,
    )
    # GCP STT (streaming) emits multiple final TranscriptionFrames for one Voicera utterance
    # because it flushes mid-sentence finals. With the default 1.0s aggregation timeout each
    # fragment would trigger its own LLM run. Raise it to 3.0s so all fragments land before
    # the tester replies.
    user_agg_timeout = 3.0 if use_gcp_stack else config.USER_AGGREGATION_TIMEOUT
    context_aggregator = llm.create_context_aggregator(
        context,
        user_params=LLMUserAggregatorParams(aggregation_timeout=user_agg_timeout),
    )

    transcript = TranscriptProcessor()
    metrics_collector = MetricsCollector()

    if use_gcp_stack:
        register_switch_language_tool(llm, stt, tts, current_lang, metrics=metrics_collector)

  
    audiobuffer = AudioBufferProcessor() if config.RECORD_CALLS else None
    if audiobuffer:

        @audiobuffer.event_handler("on_audio_data")
        async def on_audio_data(buffer, audio, sample_rate, num_channels):
            os.makedirs(RECORDINGS_DIR, exist_ok=True)
            path = os.path.join(RECORDINGS_DIR, f"{report_id}.wav")
            with wave.open(path, "wb") as wf:
                wf.setnchannels(num_channels)
                wf.setsampwidth(2)  # 16-bit PCM
                wf.setframerate(sample_rate)
                wf.writeframes(audio)
            logger.info(f"🎙️ Recording written: {path} ({len(audio)} bytes)")

    # Caller reactions listen early (VAD); audio is queued so it still passes ambient noise.
    caller_fillers = _build_caller_filler_controller(
        sims, sample_rate, metrics=metrics_collector, library_paths=library_paths
    )
    after_tts = [p for p in (ambient_noise_proc,) if p]

  
    speech_probe = (
        SpeechProbeController(
            language=language,
            after_secs=interrupt_after,
            sample_rate=sample_rate,
            sound_volume=sims["barge_in"]["sound_volume"],
            metrics=metrics_collector,
            stop_enabled=sims["barge_in"].get("probe_stop_enabled", True),
            start_enabled=sims["barge_in"].get("probe_start_enabled", True),
            caller_cough_enabled=sims["barge_in"].get("cough_enabled", False),
        )
        if speech_probes_on
        else None
    )
    barge_in = (
        BargeInController(
            style=barge_in_style,
            line=config.interrupt_line(language),
            recovery_line=config.recovery_line(language),
            after_secs=interrupt_after,
            max_count=sims["barge_in"]["real_count"],
            sample_rate=sample_rate,
            fake_count=sims["barge_in"]["fake_count"],
            fake_burst_secs=sims["barge_in"]["fake_burst_secs"],
            sound_type=barge_in_sound,
            sound_volume=sims["barge_in"]["sound_volume"],
            fake_volume=sims["barge_in"]["fake_volume"],
            metrics=metrics_collector,
            library_paths=library_paths,
        )
        if interruptions_on and not speech_probes_on
        else None
    )
    pre_stt = [
        p
        for p in (speech_probe or barge_in, caller_fillers)
        if p
    ]

    lang_switch_ctl = None  # wired after task + context exist

    pipeline = Pipeline([
        transport.input(),
        *pre_stt,
        stt,
        transcript.user(),
        context_aggregator.user(),
        llm,
        tts,
        *after_tts,
        transcript.assistant(),
        *([audiobuffer] if audiobuffer else []),  # capture audio (before output) when enabled
        transport.output(),  # emits BotStarted/Stopped when tester audio actually plays
        metrics_collector,  # after output so BotStopped -> UserStarted E2E latency is observable
        context_aggregator.assistant(),
    ])

    task = PipelineTask(
        pipeline,
        params=PipelineParams(allow_interruptions=False, enable_metrics=True),
    )
    metrics_collector.attach_to_task(task)
    bot_frame_diag = install_bot_frame_diagnostics(transport.output(), task)

    if barge_in:
        barge_in.task = task
        barge_in.context = context
    if speech_probe:
        speech_probe.task = task
        speech_probe.context = context
    if caller_fillers:
        caller_fillers.task = task
    if sims["language_switch"]["enabled"]:
        lang_switch_ctl = LanguageSwitchController(
            sequence=sims["language_switch"]["sequence"],
            metrics=metrics_collector,
            context=context,
            task=task,
            stt=stt if use_gcp_stack else None,
            tts=tts if use_gcp_stack else None,
            current_lang=current_lang if use_gcp_stack else None,
            agent_lang=agent_lang,
        )

    # Call outcome (feeds the connection / graceful-termination / mid-call-drop metrics).
    # Starts "disconnected" (connected, then ended unexpectedly); upgraded as events occur.
    outcome = {"v": "disconnected"}

    async def end_call(params):
        # The tester decided the objective is met (or unachievable). Speak the farewell,
        # then stop gracefully so it finishes playing before the EndFrame hangs up.
        farewell = (params.arguments or {}).get("farewell") or "Thank you, goodbye."
        logger.info(f"🛑 Tester invoked end_call for {call_sid} (farewell={farewell!r})")
        outcome["v"] = "completed"
        await params.result_callback({"status": "ending"})
        await task.queue_frames([TTSSpeakFrame(farewell)])
        await task.stop_when_done()

    llm.register_function("end_call", end_call)

    transcript_log: list[dict] = []
    last_activity = {"t": None}  # monotonic time of the last finalized transcript line
    watchdog = {"task": None}    # idle-watchdog task handle (started on connect)

    @transcript.event_handler("on_transcript_update")
    async def on_transcript_update(processor, frame):
        for message in frame.messages:
            ts = f"[{message.timestamp}] " if message.timestamp else ""
            # role "user" = Voicera (the agent under test); "assistant" = our tester
            logger.info(f"📝 {ts}{message.role}: {message.content}")
            mono_s = (
                round(time.monotonic() - call_started_mono["t"], 2)
                if call_started_mono["t"] is not None
                else None
            )
            transcript_log.append(
                {
                    "role": message.role,
                    "content": message.content,
                    "ts": message.timestamp,
                    "mono_s": mono_s,
                }
            )
            last_activity["t"] = time.monotonic()  # progress: reset the idle watchdog
            # Language switch: inject fires synchronously during agent's transcript event
            # (before context_aggregator.user() triggers the LLM) so the LLM's next
            # response already incorporates the 'I only know X' phrase in the new language.
            if lang_switch_ctl and message.role == "user":
                await lang_switch_ctl.on_agent_turn()
            if lang_switch_ctl and message.role == "assistant":
                lang_switch_ctl.on_tester_turn()
            if speech_probe and message.content:
                speech_probe.on_transcript(message.role, message.content)

    async def _idle_watchdog():
        """End the call if the conversation makes no progress (no new finalized turn from
        either side) for IDLE_TIMEOUT_SECS — e.g. the agent keeps deferring without answering,
        so the tester has nothing to act on and would otherwise sit silent until the carrier
        drops the call.

        Two-phase: at half the timeout, nudge Voicera ("Are you still there?").
        At full timeout, speak a farewell and stop."""
        nudged = False
        while True:
            await asyncio.sleep(3)
            t = last_activity["t"]
            if t is None:
                continue
            elapsed = time.monotonic() - t
            # GCP TTS is slower than Cartesia; give extra headroom when language switching is on.
            idle_limit = config.IDLE_TIMEOUT_SECS * (2 if use_gcp_stack else 1)
            half = idle_limit / 2

            if not nudged and elapsed > half:
                nudged = True
                nudge = "Hello, are you still there?" if language == "en" else "नमस्कार, तुम्ही अजूनही आहात का?"
                logger.info(f"⏳ No progress for {half:.0f}s; nudging Voicera on {call_sid}")
                context.add_message({"role": "assistant", "content": nudge})
                await task.queue_frames([TTSSpeakFrame(nudge)])

            elif elapsed > idle_limit:
                logger.warning(
                    f"⏳ No conversation progress for {config.IDLE_TIMEOUT_SECS:.0f}s; "
                    f"ending stalled call {call_sid}"
                )
                outcome["v"] = "timeout"
                farewell = "I'm going to hang up now — thanks for your time." if language == "en" else "मी आता फोन ठेवतो — धन्यवाद."
                await task.queue_frames([TTSSpeakFrame(farewell)])
                await asyncio.sleep(3)
                await task.stop_when_done()
                return

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info(f"🔊 Media connected for call {call_sid}; tester opening the call...")
        if audiobuffer:
            recording_start["t"] = time.time()
            await audiobuffer.start_recording()
        call_started_mono["t"] = time.monotonic()
        last_activity["t"] = time.monotonic()  # arm the idle watchdog from call start
        watchdog["task"] = asyncio.create_task(_idle_watchdog())
        # With the interruption test on, the tester does NOT open — barge-in is the only ask.
        # Otherwise play the canned opener line and pre-inject it as an assistant context
        # message. Using LLMRunFrame here caused a race: Voicera's greeting arrives while
        # the LLM is generating the opener, so the user context aggregator fires a second LLM
        # call before the first assistant turn is captured (bot still speaking → context_
        # aggregator.assistant() hasn't run yet) — the tester asked its question twice.
        # Pre-injecting the opener text makes the context stable before any user input arrives.
        if not interruptions_on or speech_probes_on:
            opener = config.opening_line(language)
            context.add_message({"role": "assistant", "content": opener})
            await task.queue_frames([TTSSpeakFrame(opener)])
            if speech_probe:
                speech_probe.note_opener_played()

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info(f"🔌 Voicera disconnected for call {call_sid}; ending pipeline")
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False)
    try:
        await runner.run(task)
    finally:
        # Stop the idle watchdog so it doesn't outlive the call.
        if watchdog["task"]:
            watchdog["task"].cancel()

        # ── Post-call report ──────────────────────────────────────────────────
        if speech_probe:
            try:
                await speech_probe.wait_for_probes_complete()
            except Exception as e:
                logger.warning(f"Speech probe completion wait failed for {call_sid}: {e}")

        _summary: dict = {}
        _transcript: list[dict] = []
        _ledger: list = []
        try:
            _summary = metrics_collector.summary()
            log_bot_frame_diagnostics(bot_frame_diag)
            logger.info(f"📊 Call metrics for {call_sid}: {_summary}")

            # Rebuild per-turn transcript from LLM context (Google TTS batches all
            # assistant turns into one on_transcript_update; context has each turn
            # separately and is always accurate).
            user_entries = [m for m in transcript_log if m["role"] == "user"]
            assistant_entries = [m for m in transcript_log if m["role"] == "assistant"]
            user_idx = 0
            asst_idx = 0
            for msg in context.messages:
                role = msg.get("role")
                if role in ("system", "tool"):
                    continue
                if role == "assistant":
                    content = msg.get("content")
                    tool_calls = msg.get("tool_calls")
                    entry = assistant_entries[asst_idx] if asst_idx < len(assistant_entries) else None
                    ts = entry.get("ts") if entry else None
                    mono_s = entry.get("mono_s") if entry else None
                    if content:
                        _transcript.append(
                            {"role": "assistant", "content": content, "ts": ts, "mono_s": mono_s}
                        )
                        asst_idx += 1
                    elif tool_calls:
                        for tc in (tool_calls if isinstance(tool_calls, list) else []):
                            fn = (tc.get("function") or {}) if isinstance(tc, dict) else {}
                            if fn.get("name") == "end_call":
                                try:
                                    import json as _json
                                    farewell = _json.loads(fn.get("arguments", "{}")).get("farewell", "")
                                    if farewell:
                                        _transcript.append(
                                            {
                                                "role": "assistant",
                                                "content": farewell,
                                                "ts": ts,
                                                "mono_s": mono_s,
                                            }
                                        )
                                        asst_idx += 1
                                except Exception:
                                    pass
                elif role == "user":
                    content = msg.get("content") or ""
                    entry = user_entries[user_idx] if user_idx < len(user_entries) else None
                    ts = entry.get("ts") if entry else None
                    mono_s = entry.get("mono_s") if entry else None
                    _transcript.append(
                        {"role": "user", "content": content, "ts": ts, "mono_s": mono_s}
                    )
                    user_idx += 1

            _ledger = metrics_collector.ledger()
        except Exception as e:
            logger.error(f"Failed to collect post-call data for {call_sid}: {e}")

        # Run build_report in a thread. Use asyncio.shield so that if the outer
        # task is cancelled (e.g. via on_client_disconnected → task.cancel()), the
        # report write is NOT cancelled — CancelledError is BaseException, not
        # Exception, so the old `except Exception` silently lost the report.
        _report_coro = asyncio.to_thread(
            build_report,
            report_id,
            run_config,
            _summary,
            _transcript,
            recording_start["t"],
            outcome["v"],
            _ledger,
        )
        try:
            await asyncio.shield(_report_coro)
        except asyncio.CancelledError:
            # Outer task was cancelled; shield keeps build_report running in the
            # thread pool, but we can't await it anymore. Log and move on.
            logger.warning(f"Report write for {call_sid} was shielded from cancellation — it will complete in background")
        except Exception as e:
            logger.error(f"Failed to build report for {call_sid}: {e}", exc_info=True)
