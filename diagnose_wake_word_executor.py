"""
Reproduces the EXACT threading context jarvis/__main__.py uses
(loop.run_in_executor) to confirm whether the hang is specific to running
inside an asyncio executor thread, as opposed to the plain main-thread
context the previous diagnostic used.

Run directly:
    python diagnose_wake_word_executor.py
"""

import asyncio
import time


def blocking_work():
    print("  [thread] importing openwakeword...")
    import openwakeword.utils
    from openwakeword.model import Model

    print("  [thread] loading model...")
    t0 = time.time()
    model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
    print(f"  [thread] model loaded in {time.time() - t0:.1f}s")

    print("  [thread] opening microphone InputStream...")
    import sounddevice as sd

    t0 = time.time()
    stream = sd.InputStream(samplerate=16000, channels=1, dtype="int16")
    with stream:
        print(f"  [thread] stream started in {time.time() - t0:.1f}s, reading one frame...")
        t0 = time.time()
        frame, overflowed = stream.read(1280)
        print(f"  [thread] read one frame in {time.time() - t0:.1f}s")

    print("  [thread] done.")
    return "success"


async def main():
    print("Running blocking_work() via loop.run_in_executor, exactly like the app does...")
    print("(if it hangs, press Ctrl+C for a traceback)")
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, blocking_work)
    print(f"\nResult: {result}")


if __name__ == "__main__":
    asyncio.run(main())
