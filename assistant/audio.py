"""Microphone capture (sounddevice) with optional silence endpointing."""
import threading
import time

import numpy as np
import sounddevice as sd

TARGET_SR = 16000


def list_input_devices():
    hostapis = sd.query_hostapis()
    out = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            out.append({"index": i, "name": d["name"], "hostapi": hostapis[d["hostapi"]]["name"],
                        "channels": d["max_input_channels"]})
    return out


def resolve_device(spec):
    """spec: None | int index | {"name": str, "hostapi": str}. Returns device index or None."""
    if spec is None:
        return None
    if isinstance(spec, int):
        return spec
    for d in list_input_devices():
        if d["name"] == spec["name"] and (not spec.get("hostapi") or d["hostapi"] == spec["hostapi"]):
            return d["index"]
    for d in list_input_devices():  # fall back to a substring match
        if spec["name"].lower() in d["name"].lower():
            return d["index"]
    raise RuntimeError(f"Input device not found: {spec}. Run: run.bat --select-mic")


class Recorder:
    def __init__(self, device=None, silence_seconds=1.0, max_seconds=20.0):
        self.device = device
        self.silence_seconds = silence_seconds
        self.max_seconds = max_seconds
        self._chunks = []
        self._stream = None
        self._lock = threading.Lock()
        self.on_auto_stop = None  # callback when silence endpointing ends a recording
        self._speech_seen = False
        self._last_voice = 0.0
        self._started = 0.0
        self._noise = 0.003
        self._endpoint = False

    def start(self, endpoint=False):
        self._endpoint = endpoint
        self._chunks = []
        self._speech_seen = False
        self._started = self._last_voice = time.time()
        info = sd.query_devices(self.device, "input")
        self._sr = int(info["default_samplerate"])
        self._stream = sd.InputStream(device=self.device, channels=1, samplerate=self._sr,
                                      dtype="float32", callback=self._cb)
        self._stream.start()

    def _cb(self, indata, frames, t, status):
        chunk = indata[:, 0].copy()
        self._chunks.append(chunk)
        if not self._endpoint:
            return
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        now = time.time()
        if rms > max(self._noise * 3, 0.01):
            self._speech_seen = True
            self._last_voice = now
        done = (self._speech_seen and now - self._last_voice > self.silence_seconds) or \
               (now - self._started > self.max_seconds)
        if done and self.on_auto_stop:
            cb, self.on_auto_stop = self.on_auto_stop, None
            threading.Thread(target=cb, daemon=True).start()

    def stop(self):
        """Returns mono float32 audio at 16 kHz."""
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if not self._chunks:
            return np.zeros(0, dtype="float32")
        audio = np.concatenate(self._chunks)
        if self._sr != TARGET_SR:
            n = int(len(audio) * TARGET_SR / self._sr)
            audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype("float32")
        return audio
