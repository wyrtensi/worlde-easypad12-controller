# WORLDE EASYPAD.12 Controller
[![Python Version](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Qt Version](https://img.shields.io/badge/Qt%20for%20Python-PySide6-green.svg)](https://www.qt.io/qt-for-python)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
>Discord: https://discord.gg/3ZHmwVuA9u
>
Adds multifunctional controls in Windows 10/11 to your favorite WORLDE EASYPAD.12
![image](https://github.com/user-attachments/assets/3454a86c-b0e0-4f52-baf0-794052dd0bd3)
![image](https://github.com/user-attachments/assets/aa17a8ea-9a23-42b3-bfb3-4513dae5b46f)
![image](https://github.com/user-attachments/assets/3caf32cc-554a-4612-846a-9d830203da49)

## Features

- Intuitive interface that matches the exact layout of your MIDI keyboard
- Easily assign different actions to each button:
  - Launch applications, files and windows apps shortcuts
  - Toggle applications
  - Open websites
  - Control system volume with the slider
  - Switch between audio output devices
  - Execute keyboard shortcuts
  - Run powershell commands
  - Run system commands
  - Media controls (play/pause, next/previous track, volume)
  - Speech to text (Google speech recognition, multilangual, hold button for it)
  - Ask ChatGPT, ask and receive answer from ChatGPT to any textfield (Uses online Whisper and reqires OpenAI API)
  - Text to speech (yandex, use Russian model only, Zahar and Jane are the best, russian accent reading English text)
  - Wake-on-LAN option
  - Web OS LG TV Control
- Customizable notifications
- Beautiful dark-themed UI with teal and pink accents
- Save and load your button configurations
- Minimize to system tray for background operation
- Detailed configuration instructions for each action type
- Not all features shown in app are available

## Prerequisites

- WORLDE EASYPAD.12 MIDI keyboard
- Windows 10/11 operating system (Tested on windows 11)

## EXE Building info
- Python 3.12 installed

		pyinstaller --onefile --noconsole --icon=icon.ico --version-file version.txt --exclude-module PyQt5 --exclude-module PyQt6 run.py

## Installation
IMPORTANT:

>Before you run the app to have all functional working run Windows PowerShell with administrative rights and use this command: 

	powershell -Command “Install-Module -Name AudioDeviceCmdlets -Force”

Then:

>Run the app in it's own root folder because it will create subfolders.
>If needed create a shortcut to add this app to autostart.

## Usage

1. Connect your WORLDE EASYPAD.12 MIDI keyboard to your computer.

2. Launch the application:

>easypad12controller.exe


3. The application will try to automatically connect to your EASYPAD.12. If it fails, click the "Connect" button and select your device from the list. Also if you run 2 of this apps at once or more only one app will able to connect, so make sure that you run only one program.

4. Configure buttons by clicking on them in the UI.

5. Test your configuration by pressing the physical buttons on your MIDI keyboard.

6. Use the slider to control system volume.

7. Minimize to tray by clicking the "Hide to Tray" button or closing the window.
