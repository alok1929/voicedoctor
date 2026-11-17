"""Tests for CallerFillerSoundsController: cough/hmm while agent speaks.

Run:  .venv/bin/python tests/test_caller_fillers.py
"""

import asyncio
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipecat.frames.frames import (
    CancelFrame,
    OutputAudioRawFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from app.bot import (
    CallerFillerSoundsController,
    _build_caller_filler_controller,
    _load_caller_filler_sound,
    _scale_pcm16_bytes,
)


OUTBOUND_SR = 8_000
CHUNK = 800


def _flat_pcm(length: int, amplitude: int = 12_000) -> bytes:
    return np.full(length, amplitude, dtype=np.int16).tobytes()


def _rms(audio_bytes: bytes) -> float:
    data = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(data ** 2)))


def _make_controller(
    cough: bool = True,
    hmm: bool = False,
    volume: float = 0.5,
) -> CallerFillerSoundsController:
    clips = {}
    if cough:
        clips["cough"] = _flat_pcm(CHUNK)
    if hmm:
        clips["hmm"] = _flat_pcm(CHUNK, amplitude=8_000)
    return CallerFillerSoundsController(
        clips=clips,
        sample_rate=OUTBOUND_SR,
        volume=volume,
    )


async def _collect_during_speech(proc: CallerFillerSoundsController, speak_secs: float = 0.15):
    collected: list[OutputAudioRawFrame] = []

    async def fake_push(frame, direction=FrameDirection.DOWNSTREAM):
        if isinstance(frame, OutputAudioRawFrame):
            collected.append(frame)

    proc.push_frame = fake_push
    # Shorten delays for tests.
    import app.config as cfg

    old_initial = cfg.CALLER_FILLER_INITIAL_DELAY_SECS
    old_min = cfg.CALLER_FILLER_MIN_INTERVAL_SECS
    old_max = cfg.CALLER_FILLER_MAX_INTERVAL_SECS
    cfg.CALLER_FILLER_INITIAL_DELAY_SECS = 0.02
    cfg.CALLER_FILLER_MIN_INTERVAL_SECS = 0.02
    cfg.CALLER_FILLER_MAX_INTERVAL_SECS = 0.03
    try:
        await proc.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(speak_secs)
        await proc.process_frame(UserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        if proc._loop_task and not proc._loop_task.done():
            await asyncio.sleep(0.05)
    finally:
        cfg.CALLER_FILLER_INITIAL_DELAY_SECS = old_initial
        cfg.CALLER_FILLER_MIN_INTERVAL_SECS = old_min
        cfg.CALLER_FILLER_MAX_INTERVAL_SECS = old_max
    return collected


def test_loop_plays_while_agent_speaking():
    proc = _make_controller(cough=True)
    out = asyncio.run(_collect_during_speech(proc))
    assert out, "expected filler audio while agent is speaking"
    assert all(_rms(f.audio) > 0 for f in out)
    print("PASS: loop_plays_while_agent_speaking")


def test_loop_stops_when_agent_stops():
    proc = _make_controller(cough=True)

    async def _run():
        collected: list[OutputAudioRawFrame] = []
        import app.config as cfg

        old_initial = cfg.CALLER_FILLER_INITIAL_DELAY_SECS
        old_min = cfg.CALLER_FILLER_MIN_INTERVAL_SECS
        old_max = cfg.CALLER_FILLER_MAX_INTERVAL_SECS
        cfg.CALLER_FILLER_INITIAL_DELAY_SECS = 0.02
        cfg.CALLER_FILLER_MIN_INTERVAL_SECS = 0.02
        cfg.CALLER_FILLER_MAX_INTERVAL_SECS = 0.03

        async def fake_push(frame, direction=FrameDirection.DOWNSTREAM):
            if isinstance(frame, OutputAudioRawFrame):
                collected.append(frame)

        proc.push_frame = fake_push
        try:
            await proc.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
            await asyncio.sleep(0.08)
            assert proc._loop_task is not None
            await proc.process_frame(UserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
            await asyncio.sleep(0.15)
            assert proc._loop_task is None or proc._loop_task.done()
        finally:
            cfg.CALLER_FILLER_INITIAL_DELAY_SECS = old_initial
            cfg.CALLER_FILLER_MIN_INTERVAL_SECS = old_min
            cfg.CALLER_FILLER_MAX_INTERVAL_SECS = old_max
        return collected

    out = asyncio.run(_run())
    assert out
    print("PASS: loop_stops_when_agent_stops")


def test_only_enabled_clips_used():
    proc = _make_controller(cough=True, hmm=False)
    assert set(proc._clips.keys()) == {"cough"}
    proc2 = _make_controller(cough=False, hmm=True)
    assert set(proc2._clips.keys()) == {"hmm"}
    print("PASS: only_enabled_clips_used")


def test_volume_scales_output():
    low = _scale_pcm16_bytes(_flat_pcm(CHUNK), 0.25)
    high = _scale_pcm16_bytes(_flat_pcm(CHUNK), 1.0)
    assert _rms(high) > _rms(low)
    print("PASS: volume_scales_output")


def test_build_returns_none_when_disabled():
    sims = {
        "barge_in": {
            "enabled": True,
            "style": "speech",
            "cough_enabled": False,
            "hmm_enabled": False,
            "filler_volume": 0.5,
        }
    }
    assert _build_caller_filler_controller(sims, OUTBOUND_SR) is None
    print("PASS: build_returns_none_when_disabled")


def test_build_works_for_speech_probes_when_cough_enabled():
    sims = {
        "barge_in": {
            "enabled": True,
            "style": "speech_probes",
            "cough_enabled": True,
            "hmm_enabled": False,
            "filler_volume": 0.5,
        }
    }
    ctrl = _build_caller_filler_controller(sims, OUTBOUND_SR)
    assert ctrl is not None
    print("PASS: build_works_for_speech_probes_when_cough_enabled")


def test_loop_restarts_on_second_agent_turn():
    proc = _make_controller(cough=True)

    async def _run():
        played: list[str] = []
        import app.config as cfg

        old_initial = cfg.CALLER_FILLER_INITIAL_DELAY_SECS
        old_min = cfg.CALLER_FILLER_MIN_INTERVAL_SECS
        old_max = cfg.CALLER_FILLER_MAX_INTERVAL_SECS
        cfg.CALLER_FILLER_INITIAL_DELAY_SECS = 0.02
        cfg.CALLER_FILLER_MIN_INTERVAL_SECS = 0.02
        cfg.CALLER_FILLER_MAX_INTERVAL_SECS = 0.03

        async def fake_play(kind, pcm):
            played.append(kind)

        proc._play_clip = fake_play
        try:
            await proc.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
            await asyncio.sleep(0.08)
            await proc.process_frame(UserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
            await asyncio.sleep(0.05)
            first_count = len(played)
            await proc.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
            await asyncio.sleep(0.08)
            await proc.process_frame(UserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
            await asyncio.sleep(0.05)
        finally:
            cfg.CALLER_FILLER_INITIAL_DELAY_SECS = old_initial
            cfg.CALLER_FILLER_MIN_INTERVAL_SECS = old_min
            cfg.CALLER_FILLER_MAX_INTERVAL_SECS = old_max
        return first_count, len(played)

    first_count, total = asyncio.run(_run())
    assert first_count > 0, "expected clips on first agent turn"
    assert total > first_count, "expected clips on second agent turn too"
    print("PASS: loop_restarts_on_second_agent_turn")


def test_cancel_stops_loop():
    proc = _make_controller(cough=True)

    async def _run():
        await proc.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        assert proc._loop_task is not None
        await proc.process_frame(CancelFrame(), FrameDirection.DOWNSTREAM)
        assert proc._loop_task is None

    asyncio.run(_run())
    print("PASS: cancel_stops_loop")


def test_load_caller_filler_sound_from_assets():
    from app import config

    for kind in ("cough", "hmm"):
        path = config.CALLER_FILLER_FILES[kind]
        if not os.path.isfile(path):
            print(f"SKIP: load_caller_filler_sound ({kind} asset missing)")
            continue
        pcm = _load_caller_filler_sound(path, OUTBOUND_SR)
        assert pcm
        assert _rms(pcm) > 0
    print("PASS: load_caller_filler_sound_from_assets")


if __name__ == "__main__":
    tests = [
        test_loop_plays_while_agent_speaking,
        test_loop_stops_when_agent_stops,
        test_only_enabled_clips_used,
        test_volume_scales_output,
        test_build_returns_none_when_disabled,
        test_build_works_for_speech_probes_when_cough_enabled,
        test_loop_restarts_on_second_agent_turn,
        test_cancel_stops_loop,
        test_load_caller_filler_sound_from_assets,
    ]
    for t in tests:
        t()
    print("\nAll caller filler tests passed.")
