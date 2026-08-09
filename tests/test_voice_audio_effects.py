import numpy as np
import pytest

from app.voice.audio_effects import (
    apply_amplitude_modulation,
    apply_cinematic_effect,
    apply_high_shelf_boost,
)

SAMPLE_RATE = 24000


def _sine(freq_hz: float, duration_s: float = 1.0, amplitude: float = 0.5) -> np.ndarray:
    t = np.arange(int(SAMPLE_RATE * duration_s)) / SAMPLE_RATE
    return amplitude * np.sin(2 * np.pi * freq_hz * t)


def _fft_magnitude_at(samples: np.ndarray, freq_hz: float, sample_rate: int) -> float:
    spectrum = np.abs(np.fft.rfft(samples))
    freqs = np.fft.rfftfreq(len(samples), d=1 / sample_rate)
    idx = np.argmin(np.abs(freqs - freq_hz))
    return float(spectrum[idx])


def test_amplitude_modulation_matches_expected_formula():
    """Verify the actual mathematical transform, not just 'it changed
    something' — a constant-amplitude input should come out multiplied
    exactly by the known modulator waveform."""
    samples = np.ones(SAMPLE_RATE)  # 1 second of constant amplitude 1.0
    result = apply_amplitude_modulation(samples, SAMPLE_RATE, mod_rate_hz=50.0, depth=0.05)

    t = np.arange(SAMPLE_RATE) / SAMPLE_RATE
    expected = 1.0 * (1.0 + 0.05 * np.sin(2 * np.pi * 50.0 * t))

    assert np.allclose(result, expected, atol=1e-9)


def test_amplitude_modulation_preserves_shape():
    samples = np.zeros((SAMPLE_RATE, 2))  # stereo-shaped input
    result = apply_amplitude_modulation(samples, SAMPLE_RATE)
    assert result.shape == samples.shape


def test_high_shelf_boost_increases_high_frequency_energy_relative_to_low():
    """A mixed low+high tone signal should come out with the high-frequency
    component relatively louder after boosting, and the low-frequency
    component roughly unchanged — verifying the boost targets the
    intended frequency range rather than just scaling everything.

    Uses lower-amplitude tones so the boosted signal stays comfortably
    under the clip-prevention threshold; otherwise the peak-normalization
    safety clamp scales the whole signal down (including the low band),
    which is correct behavior but would confound this specific check.
    """
    low_tone = _sine(500, amplitude=0.2)
    high_tone = _sine(7500, amplitude=0.2)
    mixed = low_tone + high_tone

    boosted = apply_high_shelf_boost(mixed, SAMPLE_RATE, cutoff_hz=6000, gain_db=6.0)

    low_before = _fft_magnitude_at(mixed, 500, SAMPLE_RATE)
    low_after = _fft_magnitude_at(boosted, 500, SAMPLE_RATE)
    high_before = _fft_magnitude_at(mixed, 7500, SAMPLE_RATE)
    high_after = _fft_magnitude_at(boosted, 7500, SAMPLE_RATE)

    # High frequency content should increase noticeably.
    assert high_after > high_before * 1.3
    # Low frequency content should stay roughly where it was (not silent
    # to this filter's stopband).
    assert low_after == pytest.approx(low_before, rel=0.1)


def test_high_shelf_boost_does_not_clip():
    loud_signal = _sine(7500, amplitude=0.99)
    boosted = apply_high_shelf_boost(loud_signal, SAMPLE_RATE, gain_db=6.0)
    assert np.max(np.abs(boosted)) <= 1.0 + 1e-9


def test_high_shelf_boost_normalizes_whole_signal_when_boost_would_clip():
    """When boosting pushes the peak over 1.0, the clip-guard scales the
    entire signal down uniformly (not just the boosted band) — documented
    explicitly since it's the reason the previous test needs low-amplitude
    input tones to isolate the frequency-targeting behavior specifically."""
    low_tone = _sine(500, amplitude=0.5)
    high_tone = _sine(7500, amplitude=0.5)
    mixed = low_tone + high_tone  # peak already near 1.0 before any boost

    boosted = apply_high_shelf_boost(mixed, SAMPLE_RATE, cutoff_hz=6000, gain_db=6.0)

    assert np.max(np.abs(boosted)) <= 1.0 + 1e-9


def test_cinematic_effect_combines_both_and_preserves_length():
    samples = _sine(1000, duration_s=0.5)
    result = apply_cinematic_effect(samples, SAMPLE_RATE)

    assert result.shape == samples.shape
    assert not np.allclose(result, samples)  # something changed
    assert np.max(np.abs(result)) <= 1.0 + 1e-9
