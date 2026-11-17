"""Smoke tests for the simulation metrics + report JSON.

Drives MetricsCollector with a deterministic synthetic timeline (no telephony, no
pipeline) so we can assert the new ledger-scored metrics exactly, then runs the data
through build_report and checks the emitted JSON.

Run:  .venv/bin/python -m pytest tests/test_metrics_smoke.py -q
  or: .venv/bin/python tests/test_metrics_smoke.py   (prints the report JSON)
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import metrics as M
from app.config import is_baseline_call
from app.metrics import MetricsCollector
from pipecat.frames.frames import TTSStartedFrame, TTSStoppedFrame, UserStartedSpeakingFrame


def _build_synthetic_collector():
    """A collector whose timeline we set by hand (bypassing the pipeline plumbing).

    Timeline (seconds from t0):
      - Voicera speaks: [1-3], [10-13], [20-21], [52-53]
      - Real barge-in injected at t=10.0  -> Voicera stops at 11.0  (handled, 1.0s)
      - Fake noise injected at t=20.0      -> Voicera stops at 20.5  (WRONGLY triggered)
      - Fake noise injected at t=40.0      -> no stop within window  (correctly ignored)
    """
    c = MetricsCollector()
    t0 = c._t0

    c._voicera_starts = [t0 + x for x in (1.0, 8.0, 20.0, 52.0)]
    c._voicera_stops = [t0 + x for x in (3.0, 11.0, 20.5, 53.0)]

    c.agent_response_latencies = [1.2, 2.0, 3.4, 2.6, 5.0]
    c.tester_response_latencies = [0.8, 1.1]
    c.user_speaking_secs = 18.0
    c.bot_speaking_secs = 12.0
    c.voicera_stop_after_interruption = [1.0]
    c.tester_interrupts_voicera = 1
    c.voicera_interrupts_tester = 1

    c.record_event(
        M.EV_REAL_BARGEIN, "agent_should_stop", t=t0 + 10.0, meta={"configured_after_secs": 2.0}
    )
    c.record_event(M.EV_FAKE_NOISE, "agent_should_ignore", t=t0 + 20.0)
    c.record_event(M.EV_FAKE_NOISE, "agent_should_ignore", t=t0 + 40.0)
    c.record_event(M.EV_LANG_SWITCH, "agent_should_adapt", t=t0 + 5.0)
    return c


def test_summary_metrics():
    s = _build_synthetic_collector().summary()

    assert s["agent_response_latencies"] == [1.2, 2.0, 3.4, 2.6, 5.0]
    assert s["agent_latency_p50_s"] is not None
    assert s["agent_latency_p99_s"] >= s["agent_latency_p50_s"]

    assert abs(s["interruption_detection_accuracy"] - round(2 / 3, 3)) < 1e-6
    assert s["real_bargeins"] == 1
    assert s["fake_bargeins"] == 2
    assert abs(s["interruption_response_latency_avg_s"] - 1.0) < 1e-6
    assert abs(s["barge_in_agent_talk_to_interruption_avg_s"] - 2.0) < 1e-6
    assert s["barge_in_agent_talk_to_interruption_latencies"] == [2.0]
    assert s["interruption_response_latencies"] == [1.0]
    assert abs(s["false_interruption_rate"] - 0.5) < 1e-6
    assert s["language_switches"] == 1


def test_ledger_resolution():
    led = _build_synthetic_collector().ledger()
    by_kind = {}
    for e in led:
        by_kind.setdefault(e["kind"], []).append(e)

    assert by_kind[M.EV_REAL_BARGEIN][0]["correct"] is True
    assert by_kind[M.EV_REAL_BARGEIN][0]["agent_talk_to_interruption_s"] == 2.0
    assert by_kind[M.EV_REAL_BARGEIN][0]["interruption_response_latency_s"] == 1.0
    assert by_kind[M.EV_REAL_BARGEIN][0]["configured_after_secs"] == 2.0
    assert by_kind[M.EV_FAKE_NOISE][0]["correct"] is False
    assert by_kind[M.EV_FAKE_NOISE][1]["correct"] is True


def test_no_simulations_yields_nones():
    c = MetricsCollector()
    c.agent_response_latencies = [1.0, 2.0]
    s = c.summary()
    assert s["agent_response_latencies"] == [1.0, 2.0]
    assert s["interruption_detection_accuracy"] is None
    assert s["false_interruption_rate"] is None
    assert s["agent_latency_p99_s"] is not None


def test_speaking_frames_via_observer():
    """TTSStopped -> UserStarted produces one agent_response_latency sample."""
    c = MetricsCollector()
    tts_stop = TTSStoppedFrame()
    user_start = UserStartedSpeakingFrame()
    c._observe_speaking_frame(tts_stop)
    c._observe_speaking_frame(user_start)
    c._observe_speaking_frame(user_start)  # duplicate push must not double-count
    assert c.bot_stop_count == 1
    assert c.user_start_count == 1
    assert len(c.agent_response_latencies) == 1
    assert c.agent_response_latencies[0] >= 0


def test_multiple_barge_in_latencies():
    """Each real barge-in records agent-talk→interrupt and interrupt→stop."""
    c = MetricsCollector()
    t0 = c._t0
    c._voicera_starts = [t0 + 5.0, t0 + 20.0]
    c._voicera_stops = [t0 + 8.0, t0 + 23.0]
    c.record_event(M.EV_REAL_BARGEIN, "agent_should_stop", t=t0 + 7.0, meta={"configured_after_secs": 2.0})
    c.record_event(M.EV_REAL_BARGEIN, "agent_should_stop", t=t0 + 22.0, meta={"configured_after_secs": 2.0})
    s = c.summary()
    assert s["barge_in_agent_talk_to_interruption_latencies"] == [2.0, 2.0]
    assert s["interruption_response_latencies"] == [1.0, 1.0]
    assert s["real_bargeins"] == 2


def test_caller_hmm_and_cough_count_toward_headline_metrics():
    """Regression test: a call with only caller_hmm/filler_cough noise (no
    fake_noise) must still show up in interruption_detection_accuracy and
    false_interruption_rate instead of silently reporting 100%/None.

    Mirrors a real production report where the agent falsely stopped for 14/14
    caller_hmm+filler_cough clips, yet interruption_detection_accuracy showed 1
    (only one unrelated real_bargein was scored) and false_interruption_rate
    showed None (no fake_noise events existed to score).
    """
    c = MetricsCollector()
    t0 = c._t0

    c._voicera_starts = [t0 + x for x in (1.0, 8.0, 20.0, 30.0, 40.0)]
    c._voicera_stops = [t0 + x for x in (3.0, 8.5, 20.5, 31.0, 41.0)]

    c.record_event(
        M.EV_REAL_BARGEIN, "agent_should_stop", t=t0 + 5.0, meta={"configured_after_secs": 2.0}
    )
    # Two hmm/cough clips the agent wrongly stopped for (reacted=True).
    c.record_event(M.EV_CALLER_HMM, "agent_should_ignore", t=t0 + 20.0)
    c.record_event(M.EV_FILLER_COUGH, "agent_should_ignore", t=t0 + 30.0)
    # One hmm clip the agent correctly ignored (no stop within its window).
    c.record_event(M.EV_CALLER_HMM, "agent_should_ignore", t=t0 + 60.0, window=1.0)

    s = c.summary()

    # 4 scored events total (1 real_bargein + 3 noise), 2 correct (real_bargein +
    # the ignored hmm) => 0.5, not the misleadingly perfect 1.0 the old code gave.
    assert abs(s["interruption_detection_accuracy"] - 0.5) < 1e-6
    # 2 of 3 noise events wrongly triggered a stop.
    assert abs(s["false_interruption_rate"] - (2 / 3)) < 1e-3
    assert s["noise_events"] == 3
    assert s["noise_false_stops"] == 2


def test_is_baseline_call():
    assert is_baseline_call({}) is True
    assert is_baseline_call({"simulations": {"barge_in": {"enabled": True}}}) is False
    assert is_baseline_call({"simulations": {"ambient_noise": {"enabled": True}}}) is False
    assert is_baseline_call({"test_interruptions": True}) is False


def _build_speech_probe_collector():
    """Synthetic speech-probe timeline."""
    c = MetricsCollector()
    t0 = c._t0

    c._voicera_starts = [t0 + x for x in (1.0, 8.0, 18.0, 25.0)]
    c._voicera_stops = [t0 + x for x in (3.0, 11.0, 21.0, 30.5)]

    c.record_event(M.EV_PROBE_STOP, "agent_should_stop", t=t0 + 10.0, meta={"configured_after_secs": 2.0})
    c.record_event(M.EV_PROBE_START, "agent_should_stop", t=t0 + 20.0, meta={"configured_after_secs": 2.0})
    c.record_event(M.EV_FILLER_SPEECH, "agent_should_ignore", t=t0 + 30.0, meta={"phrase": "hmm hmm"})
    c.record_event(M.EV_FILLER_COUGH, "agent_should_ignore", t=t0 + 40.0)
    return c


def test_speech_probe_summary():
    s = _build_speech_probe_collector().summary()
    assert s["speech_probe_stop_response_latency_s"] == 1.0
    assert s["speech_probe_start_response_latency_s"] == 1.0
    assert s["speech_probe_stop_correct"] is True
    assert s["speech_probe_start_correct"] is True
    assert s["speech_probe_filler_false_stops"] == 1
    assert s["speech_probe_cough_false_stop"] is False
    assert s["speech_probe_cough_correct"] is True
    # speech_probe_accuracy now scores only probe_stop/probe_start (both correct
    # here); filler_speech/filler_cough noise-ignoring failures are scored
    # separately via interruption_detection_accuracy/false_interruption_rate
    # instead of being silently folded into this probe-specific metric.
    assert abs(s["speech_probe_accuracy"] - 1.0) < 1e-6


def test_speech_probe_ledger():
    led = _build_speech_probe_collector().ledger()
    by_kind = {e["kind"]: e for e in led}
    assert by_kind[M.EV_PROBE_STOP]["correct"] is True
    assert by_kind[M.EV_PROBE_START]["correct"] is True
    assert by_kind[M.EV_FILLER_SPEECH]["correct"] is False
    assert by_kind[M.EV_FILLER_COUGH]["correct"] is True


def test_build_report_json(tmp_path=None):
    from app import report as R

    c = _build_synthetic_collector()
    run_config = {
        "call_id": "smoke-test-1",
        "voicera_number": "+910000000000",
        "language": "mr",
        "objective": "Find out the price of tomato in Thane",
        "evals": ["expected_outcome"],
        "simulations": {"barge_in": {"enabled": True}},
    }
    transcript = [
        {"role": "assistant", "content": "नमस्कार, टोमॅटोचा भाव किती?", "ts": None},
        {"role": "user", "content": "२० रुपये किलो", "ts": None},
    ]
    path = R.build_report(
        "smoke-test-1", run_config, c.summary(), transcript,
        recording_start=None, outcome="completed", ledger=c.ledger(),
    )
    data = json.load(open(path))
    assert data["outcome"] == "completed"
    assert data["summary"]["agent_response_latencies"] == [1.2, 2.0, 3.4, 2.6, 5.0]
    assert data["meta"]["is_baseline_call"] is False
    assert "ledger" in data and len(data["ledger"]) == 4
    assert data["connection"]["ended_gracefully"] is True
    return path


def test_latency_stats_pooling():
    import importlib.util

    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "evalra_backend",
        "app",
        "latency_stats.py",
    )
    spec = importlib.util.spec_from_file_location("latency_stats_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    docs = [
        {"summary": {"agent_response_latencies": [1.0, 2.0]}},
        {"summary": {"agent_response_latencies": [3.0]}},
        {"summary": {}},
    ]
    pooled, n = mod.pool_baseline_latencies(docs)
    assert pooled == [1.0, 2.0, 3.0]
    assert n == 2
    stats = mod.compute_latency_stats(pooled)
    assert stats["avg_s"] == 2.0
    assert stats["p50_s"] == 2.0
    assert stats["p99_s"] == 2.98


if __name__ == "__main__":
    p = test_build_report_json()
    print("\n=== generated report JSON ===")
    print(json.dumps(json.load(open(p)), indent=2, ensure_ascii=False))
