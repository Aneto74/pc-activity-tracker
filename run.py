"""
PC Activity Tracker — launcher.

  python run.py          # tray mode (default)
  python run.py --cmd    # console mode, no tray
"""
import sys
import os

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Pass --no-tray if --cmd argument given
if "--cmd" in sys.argv:
    sys.argv = [sys.argv[0], "--no-tray"]
else:
    sys.argv = [sys.argv[0]]

from agent.main import main
main()
