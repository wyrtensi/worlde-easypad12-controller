#!/usr/bin/env python
import os
import sys

# Add the project directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import and run the main application
from app.main import MIDIKeyboardApp

if __name__ == "__main__":
    app = MIDIKeyboardApp()
    app.mainloop() 