# WORLDE EASYPAD.12 Controller
Adds multifunctional controls for your Windows to your favorite WORLDE EASYPAD.12
![image](https://github.com/user-attachments/assets/f3975588-12e8-483c-baa8-7c4dc8bea450)
![image](https://github.com/user-attachments/assets/a953d2cf-d8a3-4fde-80c1-cd2e09ee85ba)


## Features

- Intuitive interface that matches the exact layout of your MIDI keyboard
- Easily assign different actions to each button:
  - Launch applications, files and windows apps shortcuts
  - Open websites
  - Control system volume with the slider
  - Switch between audio output devices
  - Execute keyboard shortcuts
  - Run powershell commands
  - Run system commands
  - Media controls (play/pause, next/previous track, volume)
- Beautiful dark-themed UI with teal and pink accents
- Save and load your button configurations
- Minimize to system tray for background operation
- Detailed configuration instructions for each action type
- Not all features shown in app are available

## Prerequisites

- Python 3.12 installed (only for souce files)
- WORLDE EASYPAD.12 MIDI keyboard
- Windows 10/11 operating system

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

