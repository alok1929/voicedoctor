"""Tests for AmbientNoiseProcessor: continuous noise, volume, and TTS gain.

Run:  .venv/bin/python tests/test_noise_mixer.py
"""

import asyncio
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipecat.frames.frames import (
    OutputAudioRawFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from app.bot import AmbientNoiseProcessor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

OUTBOUND_SR = 8_000
CHUNK = 320  # 40 ms @ 8 kHz (Pipecat default outbound chunk)


def _flat_noise(length: int, amplitude: int = 20_000) -> bytes:
    return np.full(length, amplitude, dtype=np.int16).tobytes()


def _rms(audio_bytes: bytes) -> float:
    data = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(data ** 2)))


def _audio_frame(samples: int, amplitude: int = 0, sr: int = OUTBOUND_SR) -> OutputAudioRawFrame:
    data = np.full(samples, amplitude, dtype=np.int16)
    return OutputAudioRawFrame(audio=data.tobytes(), sample_rate=sr, num_channels=1)


def _make_processor(
    amplitude=20_000,
    volume=0.5,
    noise_len=CHUNK * 10,
    tts_gain=1.0,
    outbound_sr: int = OUTBOUND_SR,
) -> AmbientNoiseProcessor:
    return AmbientNoiseProcessor(
        noise_data=_flat_noise(noise_len, amplitude),
        noise_sr=outbound_sr,
        volume=volume,
        outbound_sr=outbound_sr,
        tts_gain=tts_gain,
    )


async def _run(proc: AmbientNoiseProcessor, frames) -> list[OutputAudioRawFrame]:
    collected: list[OutputAudioRawFrame] = []

    async def fake_push(frame, direction=FrameDirection.DOWNSTREAM):
        if isinstance(frame, OutputAudioRawFrame):
            collected.append(frame)

    proc.push_frame = fake_push
    for frame in frames:
        await proc.process_frame(frame, FrameDirection.DOWNSTREAM)
    return collected


# ---------------------------------------------------------------------------
# Continuous noise
# ---------------------------------------------------------------------------

def test_noise_during_silence_from_background_loop():
    """Background loop injects noise while the tester is not speaking."""
    proc = _make_processor(volume=0.5)

    async def _test():
        collected: list[OutputAudioRawFrame] = []

        async def fake_push(frame, direction=FrameDirection.DOWNSTREAM):
            if isinstance(frame, OutputAudioRawFrame):
                collected.append(frame)

        proc.push_frame = fake_push
        proc._start_loop()
        await asyncio.sleep(0.12)
        await proc._stop_loop()
        assert collected, "expected noise frames from background loop"
        assert all(_rms(f.audio) > 0 for f in collected)

    asyncio.run(_test())
    print("PASS: noise_during_silence_from_background_loop")


def test_noise_mixed_under_speech():
    """Speech frames include background noise."""
    proc = _make_processor(volume=0.5)
    frames = [TTSStartedFrame(), _audio_frame(CHUNK, amplitude=8_000), TTSStoppedFrame()]
    out = asyncio.run(_run(proc, frames))
    assert len(out) == 1
    assert _rms(out[0].audio) > _rms(_audio_frame(CHUNK, amplitude=8_000).audio)
    print("PASS: noise_mixed_under_speech")


def test_mix_speech_preserves_tts_audio_frame_type():
    """Mixed speech must stay TTSAudioRawFrame so output transport emits Bot* frames."""
    proc = _make_processor(volume=0.5)
    tts_frame = TTSAudioRawFrame(
        audio=_audio_frame(CHUNK, amplitude=8_000).audio,
        sample_rate=OUTBOUND_SR,
        num_channels=1,
    )
    out = asyncio.run(_run(proc, [TTSStartedFrame(), tts_frame, TTSStoppedFrame()]))
    assert len(out) == 1
    assert isinstance(out[0], TTSAudioRawFrame)
    print("PASS: mix_speech_preserves_tts_audio_frame_type")


def test_volume_scales_linearly():
    """Higher slider volume produces proportionally higher noise RMS."""
    results = {}
    for vol in (0.1, 0.5, 1.0):
        proc = _make_processor(amplitude=16_000, volume=vol)
        out = asyncio.run(
            _run(proc, [TTSStartedFrame(), _audio_frame(CHUNK), TTSStoppedFrame()])
        )
        results[vol] = _rms(out[0].audio)
    assert results[0.1] < results[0.5] < results[1.0]
    ratio = results[0.5] / results[0.1]
    assert 4.0 < ratio < 6.0, f"expected ~5× ratio at vol 0.5/0.1, got {ratio:.2f}"
    print("PASS: volume_scales_linearly")


def test_35_percent_quieter_than_70_percent():
    """UI volume steps should be clearly distinguishable."""
    proc_lo = _make_processor(amplitude=16_000, volume=0.35)
    proc_hi = _make_processor(amplitude=16_000, volume=0.70)
    frames = [TTSStartedFrame(), _audio_frame(CHUNK), TTSStoppedFrame()]
    rms_lo = _rms(asyncio.run(_run(proc_lo, frames))[0].audio)
    rms_hi = _rms(asyncio.run(_run(proc_hi, frames))[0].audio)
    assert rms_lo < rms_hi
    ratio = rms_hi / rms_lo
    assert 1.5 < ratio < 2.5, f"expected ~2× between 35% and 70%, got {ratio:.2f}"
    print(f"PASS: 35_percent_quieter_than_70_percent  (ratio={ratio:.2f})")


def test_no_clipping_on_loud_mix():
    proc = _make_processor(amplitude=32_767, volume=1.0)
    out = asyncio.run(
        _run(proc, [TTSStartedFrame(), _audio_frame(CHUNK, amplitude=30_000), TTSStoppedFrame()])
    )
    data = np.frombuffer(out[0].audio, dtype=np.int16)
    assert np.all(np.abs(data) <= 32_767)
    print("PASS: no_clipping_on_loud_mix")


def test_noise_loops_without_gap():
    short = _flat_noise(CHUNK // 2, amplitude=20_000)
    proc = AmbientNoiseProcessor(
        noise_data=short,
        noise_sr=OUTBOUND_SR,
        volume=1.0,
        outbound_sr=OUTBOUND_SR,
    )
    frames = [TTSStartedFrame()] + [_audio_frame(CHUNK) for _ in range(5)] + [TTSStoppedFrame()]
    out = asyncio.run(_run(proc, frames))
    assert len(out) == 5
    for i, f in enumerate(out):
        assert _rms(f.audio) > 0, f"frame {i} is silent — loop broke"
    print("PASS: noise_loops_without_gap")


# ---------------------------------------------------------------------------
# TTS gain
# ---------------------------------------------------------------------------

def test_tts_gain_boosts_voice():
    speech_amp = 8_000
    frame = _audio_frame(CHUNK, amplitude=speech_amp)
    frames = [TTSStartedFrame(), frame, TTSStoppedFrame()]
    out_1x = asyncio.run(_run(_make_processor(amplitude=0, volume=0.0, tts_gain=1.0), frames))
    out_2x = asyncio.run(_run(_make_processor(amplitude=0, volume=0.0, tts_gain=2.0), frames))
    ratio = _rms(out_2x[0].audio) / _rms(out_1x[0].audio)
    assert 1.9 < ratio < 2.1, f"expected ~2× boost, got {ratio:.2f}"
    print(f"PASS: tts_gain_boosts_voice  (ratio={ratio:.2f})")


# ---------------------------------------------------------------------------
# Audibility / balance
# ---------------------------------------------------------------------------

def test_voice_always_louder_than_noise_at_defaults():
    from app.config import NOISE_PREPARE_RMS, NOISE_VOLUME, NOISE_TTS_GAIN

    noise_rms = 32_768 * NOISE_PREPARE_RMS * NOISE_VOLUME
    quiet_speech_rms = 1_125
    boosted_speech_rms = min(quiet_speech_rms * NOISE_TTS_GAIN, 32_767)

    assert boosted_speech_rms > noise_rms, (
        f"Even quiet speech ({quiet_speech_rms} → boosted {boosted_speech_rms:.0f}) "
        f"is below noise ({noise_rms:.0f}). Lower NOISE_VOLUME or raise NOISE_TTS_GAIN."
    )
    margin_db = 20 * np.log10(boosted_speech_rms / noise_rms)
    print(
        f"PASS: voice_always_louder_than_noise  "
        f"(speech {boosted_speech_rms:.0f} vs noise {noise_rms:.0f}, "
        f"+{margin_db:.1f} dB margin, NOISE_VOLUME={NOISE_VOLUME}, NOISE_TTS_GAIN={NOISE_TTS_GAIN})"
    )


def test_default_volume_is_background_not_foreground():
    from app.config import NOISE_PREPARE_RMS, NOISE_VOLUME

    effective_noise_rms = 32_768 * NOISE_PREPARE_RMS * NOISE_VOLUME
    p50_speech_rms = 2_000
    assert effective_noise_rms < p50_speech_rms, (
        f"Noise RMS ({effective_noise_rms:.0f}) ≥ p50 speech RMS ({p50_speech_rms}) "
        f"at NOISE_VOLUME={NOISE_VOLUME} — noise will be foreground, not background"
    )
    print(
        f"PASS: default_volume_is_background  "
        f"(noise≈{effective_noise_rms:.0f} RMS vs speech p50≈{p50_speech_rms}, "
        f"NOISE_VOLUME={NOISE_VOLUME})"
    )


if __name__ == "__main__":
    tests = [
        test_noise_during_silence_from_background_loop,
        test_noise_mixed_under_speech,
        test_mix_speech_preserves_tts_audio_frame_type,
        test_volume_scales_linearly,
        test_35_percent_quieter_than_70_percent,
        test_no_clipping_on_loud_mix,
        test_noise_loops_without_gap,
        test_tts_gain_boosts_voice,
        test_voice_always_louder_than_noise_at_defaults,
        test_default_volume_is_background_not_foreground,
    ]
    for t in tests:
        t()
    print("\nAll noise mixer tests passed.")
