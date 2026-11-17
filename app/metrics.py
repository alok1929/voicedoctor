"""A silent, in-pipeline metrics collector.

Sits in the Pipecat pipeline as a pass-through processor (forwards every frame
untouched) while recording deterministic latency/throughput/turn-taking signals.

We get speaker-separated timing for free from the pipeline frames (incoming =
Voicera via STT/VAD, outgoing = tester via TTS/bot-speaking), so unlike post-hoc
stereo-audio analysis we can compute interruptions / talk-ratio / latency live.

Beyond passive observation, simulation controllers (barge-in, fake noise, silence,
language switch) call `record_event(...)` to log a *ground-truth* stimulus — what we
injected and what the agent was supposed to do. At summary() time each event is
matched against the agent's observed reaction (built from the Voicera start/stop
timeline) so we can score detection accuracy, response latency, and false-trigger
rates honestly instead of guessing.
"""

import time
from collections import defaultdict

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    MetricsFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import ProcessingMetricsData, TTFBMetricsData
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# Voicera not responding within this many seconds after the tester finishes = infra issue.
INFRA_TIMEOUT_SECS = 10.0
# How long after an injected stimulus we still count the agent's reaction as caused by it.
REACTION_WINDOW_SECS = 6.0

# Ledger event kinds.
EV_REAL_BARGEIN = "real_bargein"   # tester cut in over Voicera -> Voicera SHOULD stop
EV_FAKE_NOISE = "fake_noise"       # noise burst over Voicera, tester silent -> Voicera should IGNORE
EV_LANG_SWITCH = "lang_switch"     # tester switched language -> agent should adapt (judge-scored)
EV_PROBE_STOP = "probe_stop"       # speech probe: "stop stop" -> Voicera SHOULD stop
EV_PROBE_START = "probe_start"     # speech probe: "start start" -> Voicera SHOULD stop/react
EV_FILLER_SPEECH = "filler_speech" # hmm/ho/ha fillers -> Voicera should IGNORE
EV_FILLER_COUGH = "filler_cough"  # cough clip -> Voicera should IGNORE
EV_CALLER_HMM = "caller_hmm"      # caller hmm clip while agent speaks -> Voicera should IGNORE


def _avg(xs):
    return sum(xs) / len(xs) if xs else None


def _pct(xs, p):
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _rate(numer, denom):
    return round(numer / denom, 3) if denom else None


class MetricsCollector(FrameProcessor):
    """Pass-through processor that observes frames and records call metrics."""

    def __init__(self):
        super().__init__()
        self._ttfb = defaultdict(list)        # processor name -> [seconds]
        self._processing = defaultdict(list)  # processor name -> [seconds]

        self._user_speaking = False
        self._bot_speaking = False
        self._user_started = None
        self._bot_started = None
        self._user_stopped_at = None
        self._bot_stopped_at = None
        self._last_activity_end = None  # when the line last went quiet (either side stopped)

        self.user_speaking_secs = 0.0   # Voicera (incoming)
        self.bot_speaking_secs = 0.0    # tester (outgoing)
        self.tester_response_latencies = []  # Voicera stops -> tester starts
        self.agent_response_latencies = []   # tester stops -> Voicera starts (Voicera = agent under test)
        self.voicera_interrupts_tester = 0   # Voicera starts while tester speaking
        self.tester_interrupts_voicera = 0   # tester starts while Voicera speaking
        self.voicera_stop_after_interruption = []  # how fast Voicera yields when tester cuts in

        # Ground-truth stimulus ledger + raw Voicera speech timeline for matching.
        self.events = []                 # [{kind, expected, t, window}]
        self._voicera_starts = []        # monotonic times Voicera started speaking
        self._voicera_stops = []         # monotonic times Voicera stopped speaking

        self._t0 = time.monotonic()

        # Temporary diagnostics: frame observation counts (see summary()).
        self.user_start_count = 0
        self.user_stop_count = 0
        self.bot_start_count = 0
        self.bot_stop_count = 0
        self._seen_speaking_frame_ids: set[int] = set()

    def attach_to_task(self, task) -> None:
        """Observe User/Bot speaking frames at the task level (all push_frame calls).

        BotStarted/Stopped are emitted inside transport.output() and pushed directly
        to output._next, so they may bypass an upstream MetricsCollector processor.
        The task observer sees every downstream push regardless of pipeline order.
        """
        task.add_observer(_MetricsSpeakingObserver(self))

    def _observe_speaking_frame(self, frame: Frame) -> None:
        """Record a speaking frame once (deduped by frame id)."""
        if frame.id in self._seen_speaking_frame_ids:
            return
        self._seen_speaking_frame_ids.add(frame.id)

        now = time.monotonic()

        if isinstance(frame, UserStartedSpeakingFrame):
            self.user_start_count += 1
            self._voicera_starts.append(now)
            self._user_speaking = True
            self._user_started = now
            if self._bot_speaking:
                self.voicera_interrupts_tester += 1
            if self._bot_stopped_at is not None:
                self.agent_response_latencies.append(now - self._bot_stopped_at)
                self._bot_stopped_at = None

        elif isinstance(frame, UserStoppedSpeakingFrame):
            self.user_stop_count += 1
            self._voicera_stops.append(now)
            if self._user_started is not None:
                self.user_speaking_secs += now - self._user_started
                self._user_started = None
            self._user_speaking = False
            self._user_stopped_at = now
            if getattr(self, "_interrupt_at", None):
                self.voicera_stop_after_interruption.append(now - self._interrupt_at)
                self._interrupt_at = None

        elif isinstance(frame, TTSStartedFrame):
            # Primary tester-start signal. BotStarted from transport.output() is
            # unreliable when ambient noise keeps the output audio queue non-empty
            # (BotStopped never fires). TTSStarted/Stopped track utterance bounds.
            self.bot_start_count += 1
            self._bot_speaking = True
            self._bot_started = now
            if self._user_speaking:
                self.tester_interrupts_voicera += 1
                if getattr(self, "_interrupt_at", None) is None:
                    self._interrupt_at = now
            if self._user_stopped_at is not None:
                self.tester_response_latencies.append(now - self._user_stopped_at)
                self._user_stopped_at = None

        elif isinstance(frame, TTSStoppedFrame):
            self.bot_stop_count += 1
            if self._bot_started is not None:
                self.bot_speaking_secs += now - self._bot_started
                self._bot_started = None
            self._bot_speaking = False
            self._bot_stopped_at = now

        elif isinstance(frame, BotStartedSpeakingFrame):
            # Fallback when TTS frames are absent (non-TTS tester audio).
            if self._bot_speaking:
                return
            self.bot_start_count += 1
            self._bot_speaking = True
            self._bot_started = now
            if self._user_speaking:
                self.tester_interrupts_voicera += 1
                if getattr(self, "_interrupt_at", None) is None:
                    self._interrupt_at = now
            if self._user_stopped_at is not None:
                self.tester_response_latencies.append(now - self._user_stopped_at)
                self._user_stopped_at = None

        elif isinstance(frame, BotStoppedSpeakingFrame):
            if not self._bot_speaking:
                return
            self.bot_stop_count += 1
            if self._bot_started is not None:
                self.bot_speaking_secs += now - self._bot_started
                self._bot_started = None
            self._bot_speaking = False
            self._bot_stopped_at = now

    # === Ground-truth hooks (called by simulation controllers) ===

    def record_event(self, kind: str, expected: str, window: float = REACTION_WINDOW_SECS, t=None, meta=None):
        """Log an injected stimulus so summary() can score the agent's reaction.

        `t` (monotonic) is overridable for tests; defaults to now.
        `meta` may include simulation config such as configured_after_secs.
        """
        when = time.monotonic() if t is None else t
        payload = {
            "kind": kind,
            "expected": expected,
            "t": when,
            "window": window,
            "meta": dict(meta or {}),
        }
        if kind == EV_REAL_BARGEIN:
            agent_start = self._last_at_or_before(self._voicera_starts, when)
            if agent_start is not None:
                payload["agent_talk_to_interruption_s"] = round(when - agent_start, 3)
        elif kind in (EV_PROBE_STOP, EV_PROBE_START):
            agent_start = self._last_at_or_before(self._voicera_starts, when)
            if agent_start is not None:
                payload["agent_talk_to_probe_s"] = round(when - agent_start, 3)
        self.events.append(payload)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, MetricsFrame):
            for d in frame.data:
                if isinstance(d, TTFBMetricsData):
                    proc = d.processor.lower()
                    if "llmservice" in proc or "ttsservice" in proc:
                        continue
                    self._ttfb[d.processor].append(float(d.value))
                elif isinstance(d, ProcessingMetricsData):
                    self._processing[d.processor].append(float(d.value))

        await self.push_frame(frame, direction)

    def _pick(self, table, needle):
        vals = []
        for proc, xs in table.items():
            if needle.lower() in proc.lower():
                vals.extend(xs)
        return _avg(vals)

    @staticmethod
    def _first_after(times, t, window):
        """First timestamp in `times` strictly after t and within the window, else None."""
        for x in times:
            if t < x <= t + window:
                return x
        return None

    @staticmethod
    def _last_at_or_before(times, t):
        """Most recent timestamp in `times` that is <= t, else None."""
        prior = [x for x in times if x <= t]
        return prior[-1] if prior else None

    def mark_tester_interrupt(self, t=None):
        """Ground-truth hook: tester injected an interruption over Voicera at `t`."""
        when = time.monotonic() if t is None else t
        self._interrupt_at = when
        if self._user_speaking:
            self.tester_interrupts_voicera += 1

    def _resolve_events(self):
        """Match each injected stimulus to the agent's observed reaction.

        Returns the ledger with a `reacted` flag (+ `latency_s` where relevant) and a
        derived `correct` flag (did the agent do what it was supposed to?).
        """
        resolved = []
        for e in self.events:
            kind, t, window = e["kind"], e["t"], e["window"]
            entry = {
                "kind": kind,
                "expected": e["expected"],
                "offset_s": round(t - self._t0, 2),
                "reacted": None,
                "latency_s": None,
                "agent_talk_to_interruption_s": e.get("agent_talk_to_interruption_s"),
                "agent_talk_to_probe_s": e.get("agent_talk_to_probe_s"),
                "configured_after_secs": (e.get("meta") or {}).get("configured_after_secs"),
                "probe_phrase": (e.get("meta") or {}).get("phrase"),
                "correct": None,
            }
            if kind in (EV_REAL_BARGEIN, EV_FAKE_NOISE, EV_PROBE_STOP, EV_PROBE_START, EV_FILLER_SPEECH, EV_FILLER_COUGH, EV_CALLER_HMM):
                stop = self._first_after(self._voicera_stops, t, window)
                stopped = stop is not None
                entry["reacted"] = stopped
                if stopped:
                    entry["interruption_response_latency_s"] = round(stop - t, 3)
                    entry["latency_s"] = entry["interruption_response_latency_s"]
                if kind in (EV_REAL_BARGEIN, EV_PROBE_STOP, EV_PROBE_START):
                    entry["correct"] = stopped
                elif kind in (EV_FAKE_NOISE, EV_FILLER_SPEECH, EV_FILLER_COUGH, EV_CALLER_HMM):
                    entry["correct"] = not stopped
            elif kind == EV_LANG_SWITCH:
                # Linguistic adaptation is semantic — left to the LLM judge. We only log it.
                entry["correct"] = None
            resolved.append(entry)
        return resolved

    def ledger(self) -> list:
        """The resolved ground-truth event ledger (for the report)."""
        return self._resolve_events()

    def summary(self) -> dict:
        # Temporary diagnostics — confirms whether Bot* frames reach this processor.
        print("User starts:", self.user_start_count)
        print("User stops:", self.user_stop_count)
        print("Bot starts:", self.bot_start_count)
        print("Bot stops:", self.bot_stop_count)

        duration = time.monotonic() - self._t0
        infra_timeouts = [x for x in self.agent_response_latencies if x > INFRA_TIMEOUT_SECS]
        talk = self.user_speaking_secs + self.bot_speaking_secs

        ev = self._resolve_events()
        real = [e for e in ev if e["kind"] == EV_REAL_BARGEIN]
        fake = [e for e in ev if e["kind"] == EV_FAKE_NOISE]
        probe_stop = [e for e in ev if e["kind"] == EV_PROBE_STOP]
        probe_start = [e for e in ev if e["kind"] == EV_PROBE_START]
        filler_speech = [e for e in ev if e["kind"] == EV_FILLER_SPEECH]
        filler_cough = [e for e in ev if e["kind"] == EV_FILLER_COUGH]
        caller_hmm = [e for e in ev if e["kind"] == EV_CALLER_HMM]

        # Every kind where the agent was supposed to ignore a non-speech sound.
        # These must all count toward accuracy/false-trigger rates below — a
        # call can run filler/hmm/cough simulations without any real_bargein or
        # fake_noise events, and those failures must not silently disappear.
        noise = fake + filler_speech + filler_cough + caller_hmm
        noise_stopped = [e for e in noise if e["reacted"]]

        # Interruption-detection scoring: real speech (should stop) + every
        # non-speech-noise kind (should ignore), so nothing falls out of the
        # headline accuracy number just because it wasn't a real_bargein/fake_noise event.
        scored = real + noise
        real_latencies = [e["interruption_response_latency_s"] for e in real if e.get("interruption_response_latency_s") is not None]
        agent_talk_latencies = [
            e["agent_talk_to_interruption_s"]
            for e in real
            if e.get("agent_talk_to_interruption_s") is not None
        ]

        # Speech-probe scoring stays separate from filler/cough noise scoring —
        # probes are a deliberate "stop"/"start" command, not ambient noise.
        probe_scored = probe_stop + probe_start
        probe_stop_lat = [
            e["interruption_response_latency_s"]
            for e in probe_stop
            if e.get("interruption_response_latency_s") is not None
        ]
        probe_start_lat = [
            e["interruption_response_latency_s"]
            for e in probe_start
            if e.get("interruption_response_latency_s") is not None
        ]
        # "hmm"-type filler covers both the older filler_speech kind and the
        # newer caller_hmm kind — merged so neither silently under-reports.
        filler_hmm = filler_speech + caller_hmm
        filler_false = [e for e in filler_hmm if e["reacted"]]
        cough_false = [e for e in filler_cough if e["reacted"]]

        return {
            "call_duration_secs": round(duration, 2),
            # service timings (match the full "...Service" suffix: "deepgramsttservice"
            # contains "tts", so we key on sttservice to avoid bleed)
            "avg_stt_ttfb_s": self._pick(self._ttfb, "sttservice"),
            "avg_stt_processing_s": self._pick(self._processing, "sttservice"),
            # end-to-end agent response latency (Voicera's reply time to the tester)
            "agent_response_latencies": [round(x, 3) for x in self.agent_response_latencies],
            "agent_latency_avg_s": _avg(self.agent_response_latencies),
            "agent_latency_p50_s": _pct(self.agent_response_latencies, 50),
            "agent_latency_p90_s": _pct(self.agent_response_latencies, 90),
            "agent_latency_p95_s": _pct(self.agent_response_latencies, 95),
            "agent_latency_p99_s": _pct(self.agent_response_latencies, 99),
            "tester_latency_avg_s": _avg(self.tester_response_latencies),
            "agent_turns": len(self.agent_response_latencies),
            "tester_turns": len(self.tester_response_latencies),
            # turn-taking quality
            "voicera_interrupts_tester": self.voicera_interrupts_tester,
            "tester_interrupts_voicera": self.tester_interrupts_voicera,
            "voicera_stop_after_interruption_avg_s": _avg(self.voicera_stop_after_interruption),
            # === simulation-scored metrics (None when that sim wasn't run) ===
            # Interruption detection accuracy: real barge-ins correctly yielded to +
            # every non-speech noise kind (fake_noise, filler_speech, filler_cough,
            # caller_hmm) correctly ignored, over all such events.
            "interruption_detection_accuracy": (
                _rate(sum(1 for e in scored if e["correct"]), len(scored)) if scored else None
            ),
            # Time-to-stop after a VALID (real) barge-in (interruption -> Voicera stop).
            "interruption_response_latencies": [round(x, 3) for x in real_latencies],
            "interruption_response_latency_avg_s": _avg(real_latencies),
            "interruption_response_latency_p50_s": _pct(real_latencies, 50),
            "interruption_response_latency_p99_s": _pct(real_latencies, 99),
            # Time from Voicera starting a turn to the tester barge-in inject.
            "barge_in_agent_talk_to_interruption_latencies": [round(x, 3) for x in agent_talk_latencies],
            "barge_in_agent_talk_to_interruption_avg_s": _avg(agent_talk_latencies),
            "barge_in_agent_talk_to_interruption_p50_s": _pct(agent_talk_latencies, 50),
            "barge_in_agent_talk_to_interruption_p99_s": _pct(agent_talk_latencies, 99),
            # Fraction of ALL non-speech-noise events (fake_noise, filler_speech,
            # filler_cough, caller_hmm) that WRONGLY triggered the agent to stop.
            "false_interruption_rate": (
                _rate(len(noise_stopped), len(noise)) if noise else None
            ),
            "real_bargeins": len(real),
            "fake_bargeins": len(fake),
            # Non-speech noise events beyond fake_noise (filler/cough/hmm clips),
            # broken out so it's visible these aren't silently absorbed elsewhere.
            "noise_events": len(noise),
            "noise_false_stops": len(noise_stopped),
            "language_switches": sum(1 for e in ev if e["kind"] == EV_LANG_SWITCH),
            # === speech-probe simulation (None when style != speech_probes) ===
            "speech_probe_stop_response_latency_s": _avg(probe_stop_lat),
            "speech_probe_start_response_latency_s": _avg(probe_start_lat),
            # True only if every probe_stop/probe_start event this call was handled
            # correctly (generalizes past the old single-event-only check).
            "speech_probe_stop_correct": (
                all(e["correct"] for e in probe_stop) if probe_stop else None
            ),
            "speech_probe_start_correct": (
                all(e["correct"] for e in probe_start) if probe_start else None
            ),
            "speech_probe_filler_events": len(filler_hmm) if filler_hmm else None,
            "speech_probe_filler_false_stops": len(filler_false) if filler_hmm else None,
            "speech_probe_filler_false_stop_rate": (
                _rate(len(filler_false), len(filler_hmm)) if filler_hmm else None
            ),
            # True if a cough clip falsely triggered a stop at least once this call.
            "speech_probe_cough_false_stop": (
                len(cough_false) > 0 if filler_cough else None
            ),
            "speech_probe_cough_false_stop_rate": (
                _rate(len(cough_false), len(filler_cough)) if filler_cough else None
            ),
            "speech_probe_cough_correct": (
                all(e["correct"] for e in filler_cough) if filler_cough else None
            ),
            # Speech-probe-only accuracy (probe_stop/probe_start), no longer
            # silently mixed with filler_cough noise-ignoring scores.
            "speech_probe_accuracy": (
                _rate(sum(1 for e in probe_scored if e["correct"]), len(probe_scored))
                if probe_scored
                else None
            ),
            "infra_timeout_detected": len(infra_timeouts) > 0,
            # speaking time / talk ratio (Voicera = agent under test)
            "tester_speaking_secs": round(self.bot_speaking_secs, 2),
            "voicera_speaking_secs": round(self.user_speaking_secs, 2),
            "voicera_talk_ratio": round(self.user_speaking_secs / talk, 2) if talk > 0 else None,
            "ttfb_by_processor": {
                p: _avg(v)
                for p, v in self._ttfb.items()
                if "llmservice" not in p.lower() and "ttsservice" not in p.lower()
            },
        }


class _MetricsSpeakingObserver(BaseObserver):
    """Task-level observer: records User/Bot speaking frames on every downstream push."""

    def __init__(self, collector: MetricsCollector):
        super().__init__()
        self._collector = collector

    async def on_push_frame(self, data: FramePushed):
        if data.direction != FrameDirection.DOWNSTREAM:
            return
        if isinstance(
            data.frame,
            (
                UserStartedSpeakingFrame,
                UserStoppedSpeakingFrame,
                TTSStartedFrame,
                TTSStoppedFrame,
                BotStartedSpeakingFrame,
                BotStoppedSpeakingFrame,
            ),
        ):
            self._collector._observe_speaking_frame(data.frame)


def install_bot_frame_diagnostics(output_transport, task) -> dict:
    """Temporary upstream instrumentation for BotStarted/Stopped investigation.

    Patches transport.output() and BaseOutputTransport.MediaSender hooks, and
    registers a task observer for any Bot* frame pushes anywhere in the pipeline.
    Returns a mutable stats dict; call log_bot_frame_diagnostics(stats) at end of call.
    """
    from loguru import logger

    from pipecat.frames.frames import (
        BotStartedSpeakingFrame,
        BotStoppedSpeakingFrame,
        OutputAudioRawFrame,
        TTSAudioRawFrame,
    )
    from pipecat.observers.base_observer import BaseObserver, FramePushed
    from pipecat.processors.frame_processor import FrameDirection
    from pipecat.transports.base_output import BaseOutputTransport

    stats = {
        "output_tts_audio_in": 0,
        "output_plain_audio_in": 0,
        "hook_bot_started": 0,
        "hook_bot_stopped": 0,
        "pipeline_bot_started_push": 0,
        "pipeline_bot_stopped_push": 0,
    }

    # --- transport.output(): log inbound audio frame types ---
    _orig_process_frame = output_transport.process_frame

    async def _diag_output_process_frame(frame, direction):
        if isinstance(frame, TTSAudioRawFrame):
            stats["output_tts_audio_in"] += 1
            logger.info(
                f"DIAG output.process_frame TTSAudioRawFrame bytes={len(frame.audio)} dir={direction}"
            )
        elif isinstance(frame, OutputAudioRawFrame):
            stats["output_plain_audio_in"] += 1
            if stats["output_plain_audio_in"] <= 5 or stats["output_plain_audio_in"] % 500 == 0:
                logger.info(
                    f"DIAG output.process_frame OutputAudioRawFrame "
                    f"(non-TTS) bytes={len(frame.audio)} total={stats['output_plain_audio_in']}"
                )
        await _orig_process_frame(frame, direction)

    output_transport.process_frame = _diag_output_process_frame

    # --- BaseOutputTransport.MediaSender: log when bot-speaking hooks fire ---
    if not getattr(BaseOutputTransport.MediaSender, "_evalra_diag_patched", False):
        _orig_started = BaseOutputTransport.MediaSender._bot_started_speaking
        _orig_stopped = BaseOutputTransport.MediaSender._bot_stopped_speaking

        async def _diag_bot_started(self):
            stats["hook_bot_started"] += 1
            logger.info(
                f"DIAG MediaSender._bot_started_speaking "
                f"dest={self._destination!r} count={stats['hook_bot_started']}"
            )
            await _orig_started(self)

        async def _diag_bot_stopped(self):
            stats["hook_bot_stopped"] += 1
            logger.info(
                f"DIAG MediaSender._bot_stopped_speaking "
                f"dest={self._destination!r} count={stats['hook_bot_stopped']}"
            )
            await _orig_stopped(self)

        BaseOutputTransport.MediaSender._bot_started_speaking = _diag_bot_started
        BaseOutputTransport.MediaSender._bot_stopped_speaking = _diag_bot_stopped
        BaseOutputTransport.MediaSender._evalra_diag_patched = True

    # --- Task observer: log Bot* frames pushed anywhere in the pipeline ---
    class _BotFramePushObserver(BaseObserver):
        async def on_push_frame(self, data: FramePushed):
            if data.direction != FrameDirection.DOWNSTREAM:
                return
            if isinstance(data.frame, BotStartedSpeakingFrame):
                stats["pipeline_bot_started_push"] += 1
                logger.info(
                    f"DIAG pipeline push BotStartedSpeaking "
                    f"{data.source} -> {data.destination} "
                    f"count={stats['pipeline_bot_started_push']}"
                )
            elif isinstance(data.frame, BotStoppedSpeakingFrame):
                stats["pipeline_bot_stopped_push"] += 1
                logger.info(
                    f"DIAG pipeline push BotStoppedSpeaking "
                    f"{data.source} -> {data.destination} "
                    f"count={stats['pipeline_bot_stopped_push']}"
                )

    task.add_observer(_BotFramePushObserver())
    return stats


def log_bot_frame_diagnostics(stats: dict | None) -> None:
    """Print upstream bot-frame diagnostic totals at end of call."""
    from loguru import logger

    if not stats:
        return
    logger.info(
        "DIAG upstream bot-frame totals: "
        f"output_tts_audio_in={stats['output_tts_audio_in']} "
        f"output_plain_audio_in={stats['output_plain_audio_in']} "
        f"hook_bot_started={stats['hook_bot_started']} "
        f"hook_bot_stopped={stats['hook_bot_stopped']} "
        f"pipeline_bot_started_push={stats['pipeline_bot_started_push']} "
        f"pipeline_bot_stopped_push={stats['pipeline_bot_stopped_push']}"
    )
