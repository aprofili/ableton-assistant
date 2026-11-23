"""Local speech-to-text with faster-whisper."""

PROMPT = ("Ableton Live commands: turn looping on, turn looping off, loop on, loop off, loop bars 5 to 9, metronome on, metronome off, press play, stop, "
          "count in two bars, go to bar 17, next section, previous section, chorus, verse, bridge, "
          "arm this track for recording, disarm this track, de-arm this track, intro, outro, tempo 120, locator, arrangement, session view.")


DICTATION_PROMPT = ("Chat with Claude about the Ableton assistant: Claude, Claude Code, GitHub, pull request, "
                    "Python, the pad, the dial, Ableton Live, XPPen.")


class Transcriber:
    def __init__(self, model="small.en", device="cpu", compute_type="int8", cpu_threads=0):
        import logging
        import os
        from faster_whisper import WhisperModel

        if not cpu_threads:  # default 4 leaves cores idle; use the physical cores
            cpu_threads = max(2, (os.cpu_count() or 4) // 2)
        try:
            self.model = WhisperModel(model, device=device, compute_type=compute_type, cpu_threads=cpu_threads)
        except Exception as e:  # e.g. the faster model could not be downloaded: keep working with the old one
            logging.getLogger("assistant").info("Could not load %s (%s); falling back to small.en", model, e)
            self.model = WhisperModel("small.en", device=device, compute_type=compute_type, cpu_threads=cpu_threads)

    def warm_up(self):
        import numpy as np

        self.transcribe(np.zeros(16000, dtype="float32"))

    def transcribe(self, audio, prompt=None):
        if len(audio) < 8000:  # < 0.5 s
            return ""
        segments, _ = self.model.transcribe(
            audio, language="en", beam_size=1, vad_filter=True,
            initial_prompt=prompt or PROMPT, condition_on_previous_text=False,
        )
        return " ".join(s.text.strip() for s in segments).strip()
