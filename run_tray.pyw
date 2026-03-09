"""
Запуск в трей-режиме без окна консоли.
Запускать двойным кликом или: pythonw run_tray.pyw
"""
import sys
import os

_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _root)

try:
    from agent.main import main
    main()
except Exception as e:
    import traceback
    err_file = os.path.join(_root, "data", "startup_error.txt")
    os.makedirs(os.path.dirname(err_file), exist_ok=True)
    with open(err_file, "w", encoding="utf-8") as f:
        traceback.print_exc(file=f)
