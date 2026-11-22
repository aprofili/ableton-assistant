"""Local speech-to-text with faster-whisper."""

PROMPT = ("Ableton Live commands: loop bars 5 to 9, metronome on, metronome off, press play, stop, "
          "count in two bars, go to bar 17, next section, previous section, chorus, verse, bridge, "
          "intro, outro, tempo 120, locator, arrangement, session view.")


class Transcriber:
    def __init__(self, model="small.en", device="cpu", compute_type="int8"):
        from faster_whisper import WhisperModel

        self.model = WhisperModel(model, device=device, compute_type=compute_type)

    def warm_up(self):
        import numpy as np

        self.transcribe(np.zeros(16000, dtype="float32"))

    def transcribe(self, audio):
        if len(audio) < 8000:  # < 0.5 s
            return ""
        segments, _ = self.model.transcribe(
            audio, language="en", beam_size=1, vad_filter=True,
            initial_prompt=PROMPT, condition_on_previous_text=False,
        )
        return " ".join(s.text.strip() for s in segments).strip()
