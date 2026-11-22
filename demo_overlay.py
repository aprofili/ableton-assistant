"""Shows each popup state and screenshots it to demo_*.png (verifies the overlay on your monitors)."""
import os, sys, time
ROOT = os.path.dirname(os.path.abspath(__file__)); os.chdir(ROOT); sys.path.insert(0, ROOT)
from assistant.overlay import Overlay, set_dpi_aware, monitors
from PIL import ImageGrab

set_dpi_aware()
ov = Overlay(0.85)
ov.level_fn = lambda: 0.03 + 0.02 * ((time.time() * 3) % 1)
ov.start()
time.sleep(1.0)
def shot(name):
    ImageGrab.grab(all_screens=True).save(os.path.join(ROOT, f"demo_{name}.png"))
ov.listening(); time.sleep(1.2); shot("listening")
ov.hide(); time.sleep(0.6)
ov.api_start("make a section marker saying verse at measure ten"); time.sleep(1.0); shot("api_working")
ov.api_done(True, "Marker “Verse” at bar 10"); time.sleep(1.0); shot("api_done")
time.sleep(3.5)
with open(os.path.join(ROOT, "demo_overlay.log"), "w") as f:
    f.write(f"monitors={monitors()} ok={ov.ok} scale={getattr(ov, 'scale', None)}\n")
