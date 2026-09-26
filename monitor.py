"""
Monitor — Legacy wrapper.

This file is kept for backward compatibility.
The actual monitor logic has been moved to the monitor/ package.

Usage:
    python monitor.py          # Runs the monitor loop
    from monitor import ...    # Imports from the monitor package
"""
from monitor import run_forever

if __name__ == "__main__":
    run_forever()
