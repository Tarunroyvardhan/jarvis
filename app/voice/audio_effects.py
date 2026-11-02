"""
Post-processing effects applied to synthesized speech for a more
"cinematic AI" tone: a high-frequency shelf boost for crispness, plus a
subtle low-rate amplitude modulation for a faint metallic quality.

Both functions are pure numpy transforms on float64 samples normalized to
[-1, 1] — no file I/O, no audio hardware — so they're fully testable with
synthetic signals.
"""

from __future__ import annotations

import numpy as np


def apply_high_shelf_boost(
    samples: np.ndarray,
    sample_rate: int,
    cutoff_hz: float = 7000.0,
    gain_db: float = 1.5,
) -> np.ndarray:
    """Boost frequencies above `cutoff_hz` by approximately `gain_db` dB.

    Implemented as a high-pass-filtered copy of the signal added back on
    top of the original — a standard, cheap approximation of a shelf
    filter, good enough for a subtle 1-2 dB lift rather than a precise
    parametric EQ curve.
    """
    from scipy.signal import butter, sosfilt

    sos = butter(2, cutoff_hz, btype="highpass", fs=sample_rate, output="sos")
    high_freq_component = sosfilt(sos, samples, axis=0)

    gain_linear = 10 ** (gain_db / 20) - 1
    boosted = samples + high_freq_component * gain_linear

    return _normalize_if_clipping(boosted)


def apply_amplitude_modulation(
    samples: np.ndarray,
    sample_rate: int,
    mod_rate_hz: float = 50.0,
    depth: float = 0.05,
) -> np.ndarray:
    """Apply a subtle low-rate tremolo/ring-modulation for a faint
    metallic quality. `depth` is the modulation amount (0-1); kept small
    by default so it reads as texture, not an obvious wobble.
    """
    n_samples = samples.shape[0]
    t = np.arange(n_samples) / sample_rate
    modulator = 1.0 + depth * np.sin(2 * np.pi * mod_rate_hz * t)

    if samples.ndim > 1:
        modulator = modulator[:, np.newaxis]

    return samples * modulator


def _normalize_if_clipping(samples: np.ndarray) -> np.ndarray:
    peak = np.max(np.abs(samples))
    if peak > 1.0:
        samples = samples / peak
    return samples


def apply_room_sheen(
    samples: np.ndarray,
    sample_rate: int,
    gain: float = 0.12,
) -> np.ndarray:
    """Add a few faint, very short reflections (11-37 ms) — the polished,
    "voice in the room" quality of a film AI, without the buzzy, robotic
    character that amplitude modulation gives. `gain` ~0.1-0.2 is subtle.
    """
    if gain <= 0:
        return samples
    out = samples.astype(np.float64, copy=True)
    for delay_ms, tap_gain in ((11, 1.0), (23, 0.6), (37, 0.35)):
        delay = int(sample_rate * delay_ms / 1000)
        if 0 < delay < len(out):
            out[delay:] += samples[:-delay] * gain * tap_gain
    return _normalize_if_clipping(out)


def apply_cinematic_effect(
    samples: np.ndarray,
    sample_rate: int,
    boost_cutoff_hz: float = 7000.0,
    boost_gain_db: float = 1.5,
    mod_rate_hz: float = 50.0,
    mod_depth: float = 0.05,
    room_gain: float = 0.0,
) -> np.ndarray:
    """Presence boost, optional room sheen, optional amplitude modulation."""
    processed = apply_high_shelf_boost(samples, sample_rate, boost_cutoff_hz, boost_gain_db)
    if room_gain > 0:
        processed = apply_room_sheen(processed, sample_rate, room_gain)
    if mod_depth > 0:
        processed = apply_amplitude_modulation(processed, sample_rate, mod_rate_hz, mod_depth)
    return _normalize_if_clipping(processed)
