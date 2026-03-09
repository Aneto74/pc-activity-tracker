"""
PC Activity Tracker — launcher.

  python run.py          # tray mode (default)
  python run.py --cmd    # console mode, no tray
"""
import sys
import os

_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _root)

# Pass --no-tray if --cmd argument given
if "--cmd" in sys.argv:
    sys.argv = [sys.argv[0], "--no-tray"]
else:
    sys.argv = [sys.argv[0]]

try:
    from agent.main import main
    main()
except Exception:
    import traceback
    err_file = os.path.join(_root, "data", "startup_error.txt")
    os.makedirs(os.path.dirname(err_file), exist_ok=True)
    with open(err_file, "w", encoding="utf-8") as f:
        traceback.print_exc(file=f)
    raise
