#!/usr/bin/env python3
# run.py
from PySide6.QtWidgets import QApplication
import sys
import asyncio
from qasync import QEventLoop
from app.main import MIDIKeyboardApp  # Import your app class from main.py

def main():
    # Create QApplication first, before anything else that might create widgets
    print("Creating QApplication")
    app = QApplication(sys.argv)
    print("QApplication created")

    # Set up the qasync event loop
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    # Set some basic styling (optional, adjust as needed)
    app.setStyleSheet("""
        QWidget { background-color: #2E2E2E; }
        QPushButton:hover { background-color: #555555; }
    """)

    # Create and show the main window
    window = MIDIKeyboardApp()
    window.show()

    # Start the application with the qasync event loop
    with loop:
        exit_code = loop.run_forever()
    
    loop.close()  # Explicitly close the loop
    sys.exit(exit_code)

if __name__ == "__main__":
    main()