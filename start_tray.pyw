import os
import sys
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

try:
    from assistant.app import main
    main()
except Exception:
    try:
        from assistant import updater
        if updater.rollback_on_crash():
            os.startfile(os.path.abspath(__file__))  # relaunch the restored version
    except Exception:
        pass
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    with open(os.path.join(ROOT, "logs", "startup_error.log"), "a", encoding="utf-8") as f:
        f.write(traceback.format_exc() + "\n")
    raise
