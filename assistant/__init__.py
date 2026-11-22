import os

try:
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "VERSION"), encoding="utf-8") as _f:
        __version__ = _f.read().strip()
except OSError:
    __version__ = "dev"
