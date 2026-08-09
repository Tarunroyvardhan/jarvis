"""
Standalone diagnostic for the wake-word model loading hang.

Run directly (NOT through `python -m jarvis`):
    python diagnose_wake_word.py

This bypasses asyncio and the thread executor entirely, so if it hangs,
pressing Ctrl+C here will show a clean traceback pointing at the actual
line that's stuck — unlike inside the app, where Ctrl+C mostly just shows
asyncio's own cleanup machinery instead of the real location.
"""

import time

print("Step 1: importing openwakeword...")
t0 = time.time()
import openwakeword.utils  # noqa: E402
from openwakeword.model import Model  # noqa: E402
print(f"  done in {time.time() - t0:.1f}s")

print("Step 2: downloading model files (no-op if already cached)...")
t0 = time.time()
openwakeword.utils.download_models()
print(f"  done in {time.time() - t0:.1f}s")

print("Step 3: constructing Model(wakeword_models=['hey_jarvis'], inference_framework='onnx')...")
print("  (if it hangs here, press Ctrl+C for a real traceback)")
t0 = time.time()
model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
print(f"  done in {time.time() - t0:.1f}s")

print("\nSuccess — the model loaded fine standalone.")

print("\nStep 4: opening microphone InputStream directly...")
import sounddevice as sd
print("  default input device:", sd.query_devices(kind="input"))

t0 = time.time()
stream = sd.InputStream(samplerate=16000, channels=1, dtype="int16")
print(f"  InputStream object created in {time.time() - t0:.1f}s (not yet started)")

print("  entering 'with stream:' (this actually starts capture)...")
print("  (if it hangs here, press Ctrl+C for a real traceback)")
t0 = time.time()
with stream:
    print(f"  stream started in {time.time() - t0:.1f}s")
    print("  reading one frame...")
    t0 = time.time()
    frame, overflowed = stream.read(1280)
    print(f"  read one frame in {time.time() - t0:.1f}s, overflowed={overflowed}")

print("\nStep 4 succeeded — microphone stream works fine standalone too.")
