import subprocess
import webbrowser
import os
import ctypes
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL
import json
import pyaudio
import logging
from app.notifications import NotificationManager
from app.utils import (
    ensure_app_directories,
    save_button_config,
    get_saved_button_configs,
)
import platform
import sys
import time
import threading
import importlib.util
from typing import Optional
import psutil
import socket
import struct
import re
import asyncio

# Import WebOS TV Manager
try:
    from app.webos_tv import webos_manager
    WEBOS_AVAILABLE = True
except ImportError:
    WEBOS_AVAILABLE = False

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

try:
    import pyperclip
    PYPERCLIP_AVAILABLE = True
except ImportError:
    PYPERCLIP_AVAILABLE = False

try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False

# Check for Windows-specific clipboard module
try:
    import win32clipboard
    import win32con
    WIN32CLIPBOARD_AVAILABLE = True
except ImportError:
    WIN32CLIPBOARD_AVAILABLE = False

logger = logging.getLogger("midi_keyboard.system")

# Check if pycaw is installed
pycaw_spec = importlib.util.find_spec("comtypes")
if pycaw_spec is not None:
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    has_pycaw = True
else:
    has_pycaw = False


class SystemActions:
    def __init__(self, parent=None):
        """Initialize the system actions handler"""
        self.volume_lock = threading.Lock()
        self.system = platform.system()  # Windows, Darwin (macOS), or Linux
        self.parent = parent  # Reference to parent for notification access
        self.last_input_device = None
        self.last_playback_device = None
        logger.info(f"Initializing SystemActions for {self.system}")

        # Ensure config directories exist
        config_dir, logs_dir = ensure_app_directories()

        # Path for saved button configurations
        self.config_path = os.path.join(config_dir, "button_config.json")

        # Logger
        self.logger = logger

        # Load existing configurations if available
        self.button_configs = get_saved_button_configs()

        # Notifications
        self.notification_manager = NotificationManager()  # Assuming this exists
        self.p = pyaudio.PyAudio()  # For playback device detection
        self.selected_midi_port = None  # Tracks the current MIDI input device (update when selected)

        # Initialize COM for Windows (needed for volume control)
        self.com_initialized = False
        if self.system == "Windows":
            try:
                import win32com.client

                # Initialize COM
                win32com.client.Dispatch("SAPI.SpVoice")
                self.com_initialized = True
                logger.info("COM initialized successfully for Windows")
            except ImportError:
                logger.warning("win32com not available, COM initialization skipped")
            except Exception as e:
                logger.error(f"Failed to initialize COM: {e}")

        # Try to import pycaw for volume control
        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

            self.pycaw_available = True
            # Only try to get volume interface if COM is initialized
            if self.com_initialized:
                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(
                    IAudioEndpointVolume._iid_, CLSCTX_ALL, None
                )
                self.volume = cast(interface, POINTER(IAudioEndpointVolume))
            else:
                self.volume = None
        except (ImportError, ModuleNotFoundError):
            self.pycaw_available = False
            self.volume = None
            logger.warning("pycaw not available, volume control will use PowerShell")
        except Exception as e:
            self.pycaw_available = False
            self.volume = None
            logger.error(f"Failed to initialize volume control: {e}")

        # Start device monitoring in the background
        self.check_interval = 5  # Check every 5 seconds
        self.running = True
        self.monitor_thread = threading.Thread(target=self.monitor_devices)
        self.monitor_thread.start()

    def notify(self, notification_type, message):
        """Emit a notification signal to the main thread."""
        if self.parent:
            self.parent.notification_signal.emit(message, notification_type)
        else:
            logging.warning("Cannot notify: parent is not set")

    def set_midi_port(self, port_name):
        """Set the selected MIDI input device and notify immediately."""
        self.selected_midi_port = port_name
        if port_name:
            self.notify("input_device_selected", f"MIDI input device selected: {port_name}")
        else:
            self.notify("input_device_disconnected", "MIDI input device disconnected")

    def monitor_devices(self):
        """Background thread to check for device changes and notify."""
        while self.running:
            try:
                # Check playback device
                try:
                    current_playback = self.p.get_default_output_device_info()['name']
                except Exception as e:
                    logging.error(f"Error getting default output device: {e}")
                    current_playback = None

                if self.last_playback_device is None:
                    self.last_playback_device = current_playback
                elif current_playback != self.last_playback_device:
                    if current_playback:
                        self.notify("playback_device_changed", f"Playback device switched to {current_playback}")
                    else:
                        self.notify("playback_device_disconnected", "Playback device disconnected")
                    self.last_playback_device = current_playback

                # Check input device
                if hasattr(self.parent, 'midi_controller'):
                    available_ports = self.parent.midi_controller.get_available_ports()
                    if self.selected_midi_port and self.selected_midi_port not in available_ports:
                        self.notify("input_device_disconnected", f"MIDI input device {self.selected_midi_port} disconnected")
                        self.selected_midi_port = None
            except Exception as e:
                logging.error(f"Error in device monitoring: {e}")
            time.sleep(self.check_interval)

    def __del__(self):
        """Clean up resources when the object is destroyed."""
        self.running = False
        if hasattr(self, 'monitor_thread') and self.monitor_thread and self.monitor_thread.is_alive():
            try:
                self.monitor_thread.join(timeout=2.0)
                if self.monitor_thread.is_alive():
                    logger.warning("Monitor thread did not terminate within timeout")
                else:
                    logger.debug("Monitor thread terminated successfully")
            except Exception as e:
                logger.error(f"Error joining monitor thread: {e}")
        if hasattr(self, 'p') and self.p:
            try:
                self.p.terminate()
                logger.debug("PyAudio terminated in SystemActions")
            except Exception as e:
                logger.error(f"Error terminating PyAudio in SystemActions: {e}")

    def open_application(self, path, args=""):
        """Open an application at the specified path with optional arguments"""
        if not path:
            logger.error("No application path provided")
            return False

        try:
            if args:
                full_command = f"{path} {args}"
            else:
                full_command = path

            logger.info(f"Opening application: {full_command}")

            if self.system == "Windows":
                import subprocess

                subprocess.Popen(full_command, shell=True)
            elif self.system == "Darwin":  # macOS
                os.system(f"open {path} {args}")
            else:  # Linux
                os.system(f"{path} {args} &")

            return True
        except Exception as e:
            logger.error(f"Failed to open application: {e}")
            return False

    def toggle_application(self, action_params):
        """Toggle an application: run if not running, kill if running"""
        path = action_params.get("path", "")
        args = action_params.get("args", "")
        if not path:
            logger.error("No application path provided for toggle_app action")
            return False

        # Get the executable name
        exe_name = os.path.basename(path)

        # Check if the process is running
        running = False
        for proc in psutil.process_iter(["name"]):
            if proc.info["name"] and proc.info["name"].lower() == exe_name.lower():
                running = True
                break

        if running:
            # Kill all instances of the process
            for proc in psutil.process_iter(["name"]):
                if proc.info["name"] and proc.info["name"].lower() == exe_name.lower():
                    try:
                        proc.kill()
                        logger.info(f"Killed process: {proc.info['name']}")
                    except psutil.NoSuchProcess:
                        pass
            return True
        else:
            # Start the application
            full_command = f'"{path}" {args}' if args else f'"{path}"'
            try:
                subprocess.Popen(full_command, shell=True)
                logger.info(f"Started application: {full_command}")
                return True
            except Exception as e:
                logger.error(f"Failed to start application: {e}")
                return False

    def open_website(self, action_params):
        """Open a website in the default browser"""
        try:
            url = action_params.get("url", "")
            if not url:
                logger.error("No URL provided for web action")
                return False

            # Ensure the URL has http/https prefix
            if not url.startswith(("http://", "https://", "ftp://")):
                url = "https://" + url
                logger.debug(f"Added https:// prefix to URL: {url}")

            logger.info(f"Opening URL in default browser: {url}")
            import webbrowser

            # new=2 means open in a new tab if possible
            webbrowser.open(url, new=2)
            return True
        except Exception as e:
            logger.error(f"Error opening website: {e}")
            return False

    def set_volume(self, action, value=None):
        """Adjust system volume dynamically with proper cleanup and thread safety."""
        import comtypes
        from ctypes import POINTER, cast
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        import gc  # Added for garbage collection

        with self.volume_lock:  # Ensures thread safety
            devices = None
            interface = None
            volume_interface = None
            try:
                if self.system == "Windows":
                    if self.pycaw_available:
                        # Initialize COM for this thread
                        comtypes.CoInitialize()

                        # Get the default audio device
                        devices = AudioUtilities.GetSpeakers()
                        interface = devices.Activate(
                            IAudioEndpointVolume._iid_, CLSCTX_ALL, None
                        )
                        volume_interface = cast(interface, POINTER(IAudioEndpointVolume))

                        if action == "set" and value is not None:
                            # Set volume to the exact value (0-100 scale)
                            new_vol = max(0, min(value, 100)) / 100.0  # Convert to 0.0-1.0
                            volume_interface.SetMasterVolumeLevelScalar(new_vol, None)
                            self.logger.info(f"Volume set to {value}%")
                            return True
                        elif action == "increase":
                            # Increase volume by 5%
                            current_vol = volume_interface.GetMasterVolumeLevelScalar() * 100
                            new_vol = min(current_vol + 5, 100) / 100.0
                            volume_interface.SetMasterVolumeLevelScalar(new_vol, None)
                            self.logger.info("Volume increased by 5%")
                            return True
                        elif action == "decrease":
                            # Decrease volume by 5%
                            current_vol = volume_interface.GetMasterVolumeLevelScalar() * 100
                            new_vol = max(current_vol - 5, 0) / 100.0
                            volume_interface.SetMasterVolumeLevelScalar(new_vol, None)
                            self.logger.info("Volume decreased by 5%")
                            return True
                        elif action == "mute":
                            volume_interface.SetMute(1, None)
                            self.logger.info("Volume muted")
                            return True
                        elif action == "unmute":
                            volume_interface.SetMute(0, None)
                            self.logger.info("Volume unmuted")
                            return True
                        else:
                            self.logger.warning(f"Unknown volume action: {action}")
                            return False
                    else:
                        self.logger.error("pycaw is not available. Install it with 'pip install pycaw'")
                        return False
                else:
                    self.logger.error("Volume control only supported on Windows")
                    return False

            except Exception as e:
                self.logger.error(f"Failed to control volume: {e}")
                return False

            finally:
                # Release COM objects properly
                if volume_interface is not None:
                    volume_interface.Release()
                if interface is not None:
                    interface.Release()
                if devices is not None:
                    devices.Release()
                # Clear references to allow garbage collection
                volume_interface = None
                interface = None
                devices = None
                # Force garbage collection before uninitializing COM
                gc.collect()
                comtypes.CoUninitialize()

    def switch_audio_device(self, device_name=None, device_names=None):
        """Switch between audio output devices
        
        Args:
            device_name (str, optional): Single device name to switch to
            device_names (list, optional): List of device names to cycle through in order
            
        Returns:
            bool: True if switching was successful
        """
        try:
            if self.system == "Windows":
                # If device_names is provided and not empty, it takes precedence
                if device_names and isinstance(device_names, list) and len(device_names) > 0:
                    logger.debug(f"Attempting to cycle through {len(device_names)} audio devices")
                    
                    # First check if the module is available
                    cmd = 'powershell "Get-Command -Module AudioDeviceCmdlets -ErrorAction SilentlyContinue | Measure-Object | Select-Object -ExpandProperty Count"'
                    result = subprocess.run(
                        cmd, shell=True, capture_output=True, text=True
                    )

                    if (
                        result.returncode == 0
                        and result.stdout.strip()
                        and int(result.stdout.strip()) > 0
                    ):
                        logger.info("AudioDeviceCmdlets module is available")
                        
                        # Get current device
                        cmd = 'powershell -Command "Get-AudioDevice -Playback | Select-Object -ExpandProperty Name"'
                        result = subprocess.run(
                            cmd, shell=True, capture_output=True, text=True
                        )
                        
                        if result.returncode != 0 or not result.stdout.strip():
                            logger.warning("Failed to get current audio device")
                            current_device = None
                        else:
                            current_device = result.stdout.strip()
                            logger.debug(f"Current audio device: {current_device}")
                        
                        # Find which device in the list we're currently using
                        current_index = -1
                        for i, device in enumerate(device_names):
                            if current_device and device.lower() in current_device.lower():
                                current_index = i
                                logger.debug(f"Current device matches entry {i+1}: {device}")
                                break
                        
                        # Determine the next device to use
                        if current_index >= 0:
                            # Go to the next device in the list
                            next_index = (current_index + 1) % len(device_names)
                        else:
                            # If current device not in list, start with the first one
                            next_index = 0
                            
                        next_device = device_names[next_index]
                        logger.info(f"Switching to device {next_index+1}/{len(device_names)}: {next_device}")
                        
                        # Try to find the device ID by partial name match
                        escaped_name = next_device.replace("'", "''")
                        cmd = f"powershell -Command \"Get-AudioDevice -List | Where-Object {{$_.Type -eq 'Playback' -and $_.Name -like '*{escaped_name}*'}} | Select-Object -ExpandProperty ID -First 1\""
                        result = subprocess.run(
                            cmd, shell=True, capture_output=True, text=True
                        )

                        if result.returncode == 0 and result.stdout.strip():
                            device_id = result.stdout.strip()
                            logger.debug(f"Found device ID: {device_id}")

                            # Switch using ID instead of name
                            cmd = f"powershell -Command \"Set-AudioDevice -ID '{device_id}'\""
                            result = subprocess.run(
                                cmd, shell=True, capture_output=True, text=True
                            )

                            if result.returncode == 0:
                                logger.info(f"Successfully switched to audio device: {next_device}")
                                self.notify('device_change', f"Switched to audio device: {next_device}")
                                return True
                            else:
                                logger.warning(f"Failed to switch using device ID: {result.stderr}")
                        else:
                            logger.warning(f"Could not find device ID for name: {next_device}")
                            # Try next device in list
                            if len(device_names) > 1:
                                retry_index = (next_index + 1) % len(device_names)
                                retry_device = device_names[retry_index]
                                logger.info(f"Trying next device in list: {retry_device}")
                                
                                # Try to find the device ID by partial name match
                                escaped_name = retry_device.replace("'", "''")
                                cmd = f"powershell -Command \"Get-AudioDevice -List | Where-Object {{$_.Type -eq 'Playback' -and $_.Name -like '*{escaped_name}*'}} | Select-Object -ExpandProperty ID -First 1\""
                                result = subprocess.run(
                                    cmd, shell=True, capture_output=True, text=True
                                )
                                
                                if result.returncode == 0 and result.stdout.strip():
                                    device_id = result.stdout.strip()
                                    cmd = f"powershell -Command \"Set-AudioDevice -ID '{device_id}'\""
                                    result = subprocess.run(
                                        cmd, shell=True, capture_output=True, text=True
                                    )
                                    
                                    if result.returncode == 0:
                                        logger.info(f"Successfully switched to fallback device: {retry_device}")
                                        self.notify('device_change', f"Switched to audio device: {retry_device}")
                                        return True
                                
                            # If all fails, open sound control panel
                            logger.info("Opening Sound Control Panel as fallback")
                            subprocess.run(
                                "powershell \"Start-Process control.exe -ArgumentList 'mmsys.cpl'\"",
                                shell=True,
                            )
                            return True
                    else:
                        logger.warning("AudioDeviceCmdlets module is not available")
                        # Open sound control panel
                        subprocess.run(
                            "powershell \"Start-Process control.exe -ArgumentList 'mmsys.cpl'\"",
                            shell=True,
                        )
                        logger.info("Opened Windows Sound Control Panel")
                        return True
                
                # If we got here, use the original single device_name logic
                logger.debug(f"Attempting to switch audio device: '{device_name}'")

                # Only use AudioDeviceCmdlets for audio device switching
                try:
                    # First check if the module is available
                    cmd = 'powershell "Get-Command -Module AudioDeviceCmdlets -ErrorAction SilentlyContinue | Measure-Object | Select-Object -ExpandProperty Count"'
                    result = subprocess.run(
                        cmd, shell=True, capture_output=True, text=True
                    )

                    if (
                        result.returncode == 0
                        and result.stdout.strip()
                        and int(result.stdout.strip()) > 0
                    ):
                        logger.info("AudioDeviceCmdlets module is available")

                        if device_name:
                            # Try to find the device ID by partial name match
                            escaped_name = device_name.replace("'", "''")
                            cmd = f"powershell -Command \"Get-AudioDevice -List | Where-Object {{$_.Type -eq 'Playback' -and $_.Name -like '*{escaped_name}*'}} | Select-Object -ExpandProperty ID -First 1\""
                            result = subprocess.run(
                                cmd, shell=True, capture_output=True, text=True
                            )

                            if result.returncode == 0 and result.stdout.strip():
                                device_id = result.stdout.strip()
                                logger.debug(f"Found device ID: {device_id}")

                                # Switch using ID instead of name
                                cmd = f"powershell -Command \"Set-AudioDevice -ID '{device_id}'\""
                                result = subprocess.run(
                                    cmd, shell=True, capture_output=True, text=True
                                )

                                if result.returncode == 0:
                                    logger.info(
                                        f"Successfully switched to audio device with ID: {device_id}"
                                    )
                                    self.notify('device_change', f"Switched to audio device: {device_name}")
                                    return True
                                else:
                                    logger.warning(
                                        f"Failed to switch using device ID: {result.stderr}"
                                    )
                            else:
                                logger.warning(
                                    f"Could not find device ID for name: {device_name}"
                                )
                                logger.info("Opening Sound Control Panel as fallback")
                                subprocess.run(
                                    "powershell \"Start-Process control.exe -ArgumentList 'mmsys.cpl'\"",
                                    shell=True,
                                )
                                return True
                        else:
                            # Get all playback devices with their IDs
                            cmd = "powershell -Command \"Get-AudioDevice -List | Where-Object {$_.Type -eq 'Playback'} | Select-Object -Property ID,Name | ConvertTo-Json -Compress\""
                            result = subprocess.run(
                                cmd, shell=True, capture_output=True, text=True
                            )

                            if result.returncode == 0 and result.stdout.strip():
                                try:
                                    devices_json = json.loads(result.stdout)

                                    if isinstance(devices_json, dict):
                                        devices = [devices_json]
                                    else:
                                        devices = devices_json

                                    device_ids = [
                                        device.get("ID") for device in devices
                                    ]
                                    device_names = [
                                        device.get("Name") for device in devices
                                    ]

                                    logger.debug(
                                        f"Available audio devices: {device_names}"
                                    )

                                    if not device_ids or len(device_ids) <= 1:
                                        logger.info(
                                            "Only one or no audio devices found, no need to switch"
                                        )
                                        return True

                                    cmd = 'powershell -Command "Get-AudioDevice -Playback | Select-Object -ExpandProperty ID"'
                                    result = subprocess.run(
                                        cmd, shell=True, capture_output=True, text=True
                                    )

                                    if result.returncode == 0 and result.stdout.strip():
                                        current_device_id = result.stdout.strip()

                                        cmd_name = 'powershell -Command "Get-AudioDevice -Playback | Select-Object -ExpandProperty Name"'
                                        result_name = subprocess.run(
                                            cmd_name,
                                            shell=True,
                                            capture_output=True,
                                            text=True,
                                        )
                                        current_device = (
                                            result_name.stdout.strip()
                                            if result_name.returncode == 0
                                            else "Unknown"
                                        )

                                        logger.debug(
                                            f"Current active device: {current_device}"
                                        )

                                        try:
                                            if current_device_id in device_ids:
                                                current_index = device_ids.index(
                                                    current_device_id
                                                )
                                                next_index = (current_index + 1) % len(
                                                    device_ids
                                                )
                                                next_device_id = device_ids[next_index]
                                                next_device_name = (
                                                    device_names[next_index]
                                                    if next_index < len(device_names)
                                                    else "Unknown"
                                                )

                                                logger.debug(
                                                    f"Switching from device index {current_index} to index {next_index}"
                                                )
                                                logger.info(
                                                    f"Switching from '{current_device}' to '{next_device_name}'"
                                                )

                                                cmd = f"powershell -Command \"Set-AudioDevice -ID '{next_device_id}'\""
                                                result = subprocess.run(
                                                    cmd,
                                                    shell=True,
                                                    capture_output=True,
                                                    text=True,
                                                )

                                                if result.returncode == 0:
                                                    time.sleep(0.5)
                                                    cmd_verify = 'powershell -Command "Get-AudioDevice -Playback | Select-Object -ExpandProperty ID"'
                                                    result_verify = subprocess.run(
                                                        cmd_verify,
                                                        shell=True,
                                                        capture_output=True,
                                                        text=True,
                                                    )

                                                    if (
                                                        result_verify.returncode == 0
                                                        and result_verify.stdout.strip()
                                                        == next_device_id
                                                    ):
                                                        logger.info(
                                                            f"Verified switch to audio device: {next_device_name}"
                                                        )
                                                        self.notify('device_change', f"Switched to audio device: {next_device_name}")
                                                        return True
                                                    else:
                                                        logger.warning(
                                                            "Device switch command succeeded but verification failed"
                                                        )
                                                        cmd_alt = f"powershell -Command \"$device = Get-AudioDevice -List | Where-Object {{$_.ID -eq '{next_device_id}'}}; $device | Set-AudioDevice\""
                                                        result_alt = subprocess.run(
                                                            cmd_alt,
                                                            shell=True,
                                                            capture_output=True,
                                                            text=True,
                                                        )

                                                        if result_alt.returncode == 0:
                                                            logger.info(
                                                                "Successfully switched using alternative method"
                                                            )
                                                            self.notify('device_change', f"Switched to audio device: {next_device_name}")
                                                            return True
                                                else:
                                                    logger.warning(
                                                        f"Failed to switch device using ID: {result.stderr}"
                                                    )
                                            else:
                                                logger.warning(
                                                    f"Current device ID '{current_device_id}' not found in device list"
                                                )
                                                next_device_id = device_ids[0]
                                                next_device_name = (
                                                    device_names[0]
                                                    if len(device_names) > 0
                                                    else "Unknown"
                                                )

                                                logger.info(
                                                    f"Switching to first available device: '{next_device_name}'"
                                                )
                                                cmd = f"powershell -Command \"Set-AudioDevice -ID '{next_device_id}'\""
                                                result = subprocess.run(
                                                    cmd,
                                                    shell=True,
                                                    capture_output=True,
                                                    text=True,
                                                )

                                                if result.returncode == 0:
                                                    logger.info(
                                                        f"Successfully switched to audio device: {next_device_name}"
                                                    )
                                                    self.notify('device_change', f"Switched to audio device: {next_device_name}")
                                                    return True
                                        except Exception as e:
                                            logger.error(
                                                f"Error during device switching: {e}"
                                            )
                                    else:
                                        logger.warning(
                                            "Failed to get current audio device"
                                        )
                                except Exception as e:
                                    logger.error(
                                        f"Error parsing device information: {e}"
                                    )
                            else:
                                logger.warning("Failed to get available audio devices")
                    else:
                        logger.warning("AudioDeviceCmdlets module is not available")
                        subprocess.run(
                            "powershell \"Start-Process control.exe -ArgumentList 'mmsys.cpl'\"",
                            shell=True,
                        )
                        logger.info("Opened Windows Sound Control Panel")
                        return True
                except Exception as e:
                    logger.error(f"Error using AudioDeviceCmdlets: {e}")

                logger.info("Using fallback method: Opening Sound Control Panel")
                subprocess.run(
                    "powershell \"Start-Process control.exe -ArgumentList 'mmsys.cpl'\"",
                    shell=True,
                )
                logger.info("Opened Windows Sound Control Panel")
                return True

            elif self.system == "Darwin":  # macOS
                logger.error("Audio device switching not implemented for macOS")
                return False

            else:  # Linux
                logger.error("Audio device switching not implemented for Linux")
                return False

        except Exception as e:
            logger.error(f"Failed to switch audio device: {e}")
            return False

    def send_shortcut(self, shortcut):
        """Send a keyboard shortcut combination"""
        if not shortcut:
            logger.error("No shortcut specified")
            return False

        try:
            if not PYAUTOGUI_AVAILABLE:
                logger.error(
                    "pyautogui is not available, keyboard shortcuts cannot be sent"
                )
                return False

            logger.info(f"Sending keyboard shortcut: {shortcut}")

            key_mapping = {
                "win": "winleft",
                "windows": "winleft",
                "cmd": "command",
                "command": "command",
                "opt": "option",
                "option": "option",
                "alt": "alt",
                "control": "ctrl",
                "ctrl": "ctrl",
                "shift": "shift",
                "return": "enter",
                "enter": "enter",
                "esc": "escape",
                "escape": "escape",
                "home": "home",
                "end": "end",
                "pageup": "pageup",
                "pagedown": "pagedown",
                "insert": "insert",
                "delete": "delete",
                "del": "delete",
                "backspace": "backspace",
                "bksp": "backspace",
                "tab": "tab",
                "capslock": "capslock",
                "space": "space",
                "prtsc": "printscreen",
                "printscreen": "printscreen",
                "scrolllock": "scrolllock",
                "pause": "pause",
                "break": "pause",
                "numlock": "numlock",
            }

            for i in range(1, 13):
                key_mapping[f"f{i}"] = f"f{i}"

            keys = [k.strip().lower() for k in shortcut.split("+")]
            normalized_keys = []

            for key in keys:
                normalized_key = key_mapping.get(key, key)
                normalized_keys.append(normalized_key)

            pyautogui.hotkey(*normalized_keys)
            logger.info(f"Keyboard shortcut sent: {shortcut}")
            return True

        except Exception as e:
            logger.error(f"Failed to send keyboard shortcut: {e}")
            return False

    def media_control(self, control):
        """Control media playback using keyboard shortcuts"""
        if not PYAUTOGUI_AVAILABLE:
            logger.error("pyautogui not available for media control")
            return False

        control = standardize_media_control(control)
        logger.debug(f"Standardized media control: {control}")
        logger.info(f"Media control '{control}' sent using keyboard library")

        try:
            if control == "play_pause":
                pyautogui.press("playpause")
                # Use notify method instead of direct notification_manager access
                self.notify("play_pause_track", "Play/Pause")
                return True
            elif control == "next" or control == "next_track":
                pyautogui.press("nexttrack")
                self.notify("music_track", "Skipped to next track")
                return True
            elif control == "previous" or control == "previous_track" or control == "prev_track":
                pyautogui.press("prevtrack")
                self.notify("music_track", "Returned to previous track")
                return True
            elif control == "stop":
                pyautogui.press("stop")
                self.notify("music_track", "Media playback stopped")
                return True
            elif control == "mute" or control == "volume_mute":
                pyautogui.press("volumemute")
                self.notify("volume_adjustment", "Volume muted")
                return True
            elif control == "volume_up":
                pyautogui.press("volumeup")
                self.notify("volume_adjustment", "Volume increased")
                return True
            elif control == "volume_down":
                pyautogui.press("volumedown")
                self.notify("volume_adjustment", "Volume decreased")
                return True
            else:
                logger.warning(f"Unknown media control command: {control}")
                return False
        except Exception as e:
            logger.error(f"Error sending media control: {e}")
            return False

    def save_button_config(
        self, button_id, action_type, action_data, name=None, enabled=True
    ):
        """Save button action configuration"""
        config = {
            "action_type": action_type,
            "action_data": action_data,
            "enabled": enabled,
        }

        if name:
            config["name"] = name

        success = save_button_config(button_id, config)

        if success:
            logger.info(f"Saved configuration for button {button_id}: {action_type}")
            return True, "Configuration saved"
        else:
            logger.error(f"Failed to save configuration for button {button_id}")
            return False, "Failed to save configuration"

    def load_button_configs(self):
        """Load saved button configurations from file"""
        try:
            configs = get_saved_button_configs()
            if configs:
                logger.info(f"Loaded {len(configs)} button configurations")
                return configs

            if os.path.exists(self.config_path):
                try:
                    with open(self.config_path, "r") as f:
                        old_configs = json.load(f)
                    logger.info(
                        f"Loaded {len(old_configs)} button configurations from legacy file"
                    )
                    return old_configs
                except Exception as e:
                    logger.error(
                        f"Error loading button configurations from legacy file: {e}"
                    )

            logger.info("No saved button configurations found")
            return {}
        except Exception as e:
            logger.error(f"Error in load_button_configs: {e}")
            return {}

    def execute_action(self, action_type, action_params):
        """Execute the specified action with the given parameters"""
        logger.debug(f"Executing action: {action_type} with params: {action_params}")

        try:
            if isinstance(action_params, str):
                try:
                    action_params = json.loads(action_params)
                except json.JSONDecodeError:
                    action_params = {"value": action_params}

            if action_params is None:
                action_params = {}
            elif not isinstance(action_params, dict):
                action_params = {"value": action_params}

            if action_type == "app":
                return self.launch_application(action_params)

            elif action_type == "toggle_app":
                return self.toggle_application(action_params)

            elif action_type == "web":
                return self.open_website(action_params)

            elif action_type == "volume":
                return self.control_volume(action_params)

            elif action_type == "media":
                return self.control_media(action_params)

            elif action_type == "shortcut":
                shortcut = action_params.get("shortcut", "")
                if not shortcut:
                    logger.error("No shortcut specified in parameters")
                    return False
                return self.send_shortcut(shortcut)

            elif action_type == "audio_device":
                device_name = action_params.get("device_name", "")
                device_names = action_params.get("device_names", [])
                logger.debug(
                    f"Audio device switching requested with device_name: '{device_name}' and device_names: {device_names}"
                )
                result = self.switch_audio_device(device_name, device_names)
                logger.debug(f"Audio device switching result: {result}")
                return result

            elif action_type == "text":
                return self.type_text(action_params)

            elif action_type == "command":
                commands = action_params.get("commands", [])
                if not commands:
                    logger.error("No commands specified for command action")
                    return False
                threading.Thread(
                    target=self.execute_commands_with_delays, args=(commands,)
                ).start()
                return True

            elif action_type == "window":
                return self.control_window(action_params)

            elif action_type == "mouse":
                return self.control_mouse(action_params)

            elif action_type == "setting":
                return self.toggle_setting(action_params)

            elif action_type == "powershell":
                commands = action_params.get("commands", [])
                if not commands:
                    logger.error("No PowerShell commands specified")
                    return False
                threading.Thread(
                    target=self.execute_powershell_commands_with_delays,
                    args=(commands,),
                ).start()
                return True

            elif action_type == "text_to_speech":
                return self.text_to_speech(action_params)
                
            elif action_type == "wake_on_lan":
                return self.wake_on_lan(action_params)
                
            elif action_type == "webos_tv":
                return self.control_webos_tv(action_params)

            else:
                logger.error(f"Unknown action type: {action_type}")
                return False

        except Exception as e:
            logger.error(f"Error executing action: {e}")
            return False

    def launch_application(self, action_params):
        """Launch an application"""
        try:
            app_path = action_params.get("path", "")
            if not app_path:
                logger.error("No application path provided for app action")
                return False

            logger.info(f"Launching application: {app_path}")

            if os.name == "nt":  # Windows
                subprocess.Popen(f'start "" "{app_path}"', shell=True)
            elif os.name == "posix":  # macOS or Linux
                if sys.platform == "darwin":  # macOS
                    subprocess.Popen(["open", app_path])
                else:  # Linux
                    subprocess.Popen([app_path])

            return True
        except Exception as e:
            logger.error(f"Error launching application: {e}")
            return False

    def control_volume(self, params):
        action = params.get("action", "increase")
        value = params.get("value", None)
        return self.set_volume(action, value)

    def control_media(self, params):
        control_type = params.get("control", "play_pause")
        return self.media_control(control_type)

    def trigger_key_combo(self, params):
        shortcut = params.get("shortcut", "")
        return self.send_shortcut(shortcut)

    def type_text(self, params):
        """Type text automatically"""
        try:
            if not PYAUTOGUI_AVAILABLE:
                logger.error("pyautogui is not available, text cannot be typed")
                return False

            text = params.get("text", "")
            if not text:
                logger.error("No text specified for typing")
                return False

            # Get optimization parameters
            force_unicode = params.get("force_unicode", True)  # Default to True for language preservation
            typing_speed = params.get("typing_speed", "fast")  # 'fast', 'balanced', 'reliable', 'auto'
            
            # Text length will determine the optimal strategy
            text_length = len(text)
            logger.info(f"Typing text ({text_length} chars): {text[:20]}...")
            
            # Auto-select speed based on text length
            if typing_speed == "auto":
                if text_length <= 20:
                    typing_speed = "reliable"  # For very short texts, prioritize reliability
                elif text_length <= 100:
                    typing_speed = "balanced"  # For medium texts, use balanced approach
                else:
                    typing_speed = "fast"      # For long texts, prioritize speed
            
            # Determine character delay based on typing_speed
            char_delay = 0.01  # Default
            if typing_speed == "fast":
                char_delay = 0.005
            elif typing_speed == "balanced":
                char_delay = 0.01
            elif typing_speed == "reliable":
                char_delay = 0.02
                
            # ----- STRATEGY SELECTION: PRIORITIZE BY TEXT LENGTH -----
            
            # For longer texts, clipboard is much faster
            if text_length > 50 or typing_speed == "fast":
                # Try clipboard method first for longer texts (fastest)
                if self.system == "Windows":
                    clipboard_success = self.paste_text(text)
                    if clipboard_success:
                        return True
                elif PYPERCLIP_AVAILABLE:
                    clipboard_success = self.paste_text(text)
                    if clipboard_success:
                        return True
            
            # For Unicode text on Windows, use SendInput with batched characters
            if force_unicode and self.system == "Windows" and text_length <= 500:
                # For medium-length texts, batch SendInput is efficient
                batch_size = 10 if typing_speed == "fast" else 5
                success = self._type_text_unicode_batch(text, batch_size, char_delay)
                if success:
                    return True
            
            # For short texts or if previous methods failed, try pyautogui
            if text_length <= 100:
                try:
                    if typing_speed == "fast":
                        # For short texts, pyautogui.write is fast
                        pyautogui.write(text)
                    else:
                        # Safer character by character approach for better reliability
                        for char in text:
                            pyautogui.write(char)
                            time.sleep(char_delay) 
                    logger.info("Text typed using pyautogui")
                    return True
                except Exception as e:
                    logger.warning(f"Failed to type text with pyautogui: {e}")
            
            # If we're here, either text is very long or previous methods failed
            # Try clipboard method as fallback (most reliable for long text)
            if self.system == "Windows":
                clipboard_success = self.paste_text(text)
                if clipboard_success:
                    return True
            
            if PYPERCLIP_AVAILABLE:
                clipboard_success = self.paste_text(text)
                if clipboard_success:
                    return True
            
            # Ultimate fallback - character by character with minimal delay
            logger.info("Using character-by-character typing as last resort")
            try:
                for char in text:
                    try:
                        pyautogui.write(char)
                        time.sleep(0.01)  # Minimal delay
                    except Exception as char_err:
                        logger.warning(f"Failed to type character {char}: {char_err}")
                return True
            except Exception as char_err:
                logger.error(f"Character-by-character typing failed: {char_err}")
                
            logger.error("All typing methods failed")
            return False
            
        except Exception as e:
            logger.error(f"Failed to type text: {e}")
            return False
            
    def _type_text_unicode_batch(self, text, batch_size=5, char_delay=0.01):
        """Type Unicode text using batched SendInput for better performance"""
        try:
            import ctypes
            from ctypes import wintypes
            
            # Define constants for SendInput
            KEYEVENTF_UNICODE = 0x0004
            KEYEVENTF_KEYUP = 0x0002
            INPUT_KEYBOARD = 1
            
            # Define the input structure
            class KEYBDINPUT(ctypes.Structure):
                _fields_ = [
                    ("wVk", wintypes.WORD),
                    ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))
                ]
            
            class INPUT_union(ctypes.Union):
                _fields_ = [
                    ("ki", KEYBDINPUT),
                    ("padding", ctypes.c_byte * 32)  # Ensure the union is large enough
                ]
            
            class INPUT(ctypes.Structure):
                _fields_ = [
                    ("type", wintypes.DWORD),
                    ("union", INPUT_union)
                ]
            
            # Process characters in batches
            i = 0
            total_chars = len(text)
            success = True
            
            while i < total_chars:
                # Determine batch size (handle the last batch correctly)
                end_idx = min(i + batch_size, total_chars)
                current_batch = text[i:end_idx]
                batch_len = len(current_batch)
                
                # Create an array of inputs (2 inputs per character - down and up)
                inputs = (INPUT * (batch_len * 2))()
                
                # Fill the array with key events for each character
                for j, char in enumerate(current_batch):
                    char_code = ord(char)
                    
                    # Key down
                    inputs[j*2].type = INPUT_KEYBOARD
                    inputs[j*2].union.ki.wVk = 0  # We're using Unicode, so virtual key is 0
                    inputs[j*2].union.ki.wScan = char_code
                    inputs[j*2].union.ki.dwFlags = KEYEVENTF_UNICODE
                    inputs[j*2].union.ki.time = 0
                    inputs[j*2].union.ki.dwExtraInfo = ctypes.pointer(wintypes.ULONG(0))
                    
                    # Key up
                    inputs[j*2+1].type = INPUT_KEYBOARD
                    inputs[j*2+1].union.ki.wVk = 0
                    inputs[j*2+1].union.ki.wScan = char_code
                    inputs[j*2+1].union.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
                    inputs[j*2+1].union.ki.time = 0
                    inputs[j*2+1].union.ki.dwExtraInfo = ctypes.pointer(wintypes.ULONG(0))
                
                # Send the batch of inputs
                result = ctypes.windll.user32.SendInput(batch_len * 2, ctypes.pointer(inputs), ctypes.sizeof(INPUT))
                
                # Check if all inputs were sent successfully
                if result != batch_len * 2:
                    logger.warning(f"Failed to send all characters in batch {i//batch_size + 1}")
                    success = False
                
                # Small delay between batches
                time.sleep(char_delay)
                
                # Move to next batch
                i = end_idx
            
            logger.info(f"Sent {total_chars} characters using batched Unicode SendInput")
            return success
            
        except Exception as e:
            logger.warning(f"Unicode batch typing failed: {e}")
            return False
    
    def paste_text(self, text):
        """Paste text using multiple fallback methods"""
        try:
            # First try Win32 API
            if WIN32CLIPBOARD_AVAILABLE:
                try:
                    import win32clipboard
                    import win32con
                    
                    # Save original clipboard content
                    win32clipboard.OpenClipboard()
                    try:
                        original_text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT) if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT) else ""
                    except:
                        original_text = ""
                    win32clipboard.CloseClipboard()
                    
                    # Set new text
                    win32clipboard.OpenClipboard()
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
                    win32clipboard.CloseClipboard()
                    
                    # Send Ctrl+V
                    import ctypes
                    KEYEVENTF_KEYUP = 0x0002
                    VK_CONTROL = 0x11
                    VK_V = 0x56
                    
                    ctypes.windll.user32.keybd_event(VK_CONTROL, 0, 0, 0)  # Ctrl down
                    ctypes.windll.user32.keybd_event(VK_V, 0, 0, 0)  # V down
                    time.sleep(0.1)
                    ctypes.windll.user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)  # V up
                    ctypes.windll.user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)  # Ctrl up
                    
                    # Wait for paste to complete
                    time.sleep(0.5)
                    
                    # Restore original clipboard
                    win32clipboard.OpenClipboard()
                    win32clipboard.EmptyClipboard()
                    if original_text:
                        win32clipboard.SetClipboardText(original_text, win32con.CF_UNICODETEXT)
                    win32clipboard.CloseClipboard()
                    
                    logger.info("Text pasted using Win32 API")
                    return True
                except Exception as e:
                    logger.warning(f"Win32 clipboard operation failed: {e}")
            
            # Try pyperclip
            if PYPERCLIP_AVAILABLE:
                try:
                    # Save original clipboard
                    original_text = pyperclip.paste()
                    
                    # Set new text
                    pyperclip.copy(text)
                    time.sleep(0.1)
                    
                    # Send Ctrl+V using pyautogui
                    if PYAUTOGUI_AVAILABLE:
                        pyautogui.hotkey('ctrl', 'v')
                        time.sleep(0.5)
                        
                        # Restore original clipboard
                        pyperclip.copy(original_text)
                        
                        logger.info("Text pasted using pyperclip and pyautogui")
                        return True
                except Exception as e:
                    logger.warning(f"Pyperclip paste operation failed: {e}")
            
            # PowerShell fallback
            try:
                # Escape special characters
                escaped_text = text.replace('"', '`"').replace('$', '`$').replace('`', '``')
                
                # Create PowerShell command
                ps_command = f'''
                $text = "{escaped_text}"
                Set-Clipboard -Value $text
                [System.Windows.Forms.SendKeys]::SendWait("^v")
                Start-Sleep -Milliseconds 500
                '''
                
                # Execute PowerShell command
                subprocess.run(['powershell', '-Command', ps_command], capture_output=True, text=True)
                logger.info("Text pasted using PowerShell")
                return True
                
            except Exception as e:
                logger.error(f"PowerShell paste operation failed: {e}")
                return False
                
        except Exception as e:
            logger.error(f"All paste methods failed: {e}")
            return False

    def run_command(self, params):
        """Run a system command"""
        try:
            command = params.get("command", "")
            if not command:
                logger.error("No command specified")
                return False

            logger.info(f"Running command: {command}")

            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            logger.info(f"Command started: {command}")
            return True
        except Exception as e:
            logger.error(f"Failed to run command: {e}")
            return False

    def control_window(self, params):
        """Control window (maximize, minimize, close)"""
        try:
            if not PYAUTOGUI_AVAILABLE:
                logger.error("pyautogui is not available, window control not possible")
                return False

            action = params.get("action", "")
            if not action:
                logger.error("No window action specified")
                return False

            if action == "maximize":
                pyautogui.hotkey("alt", "space")
                pyautogui.press("x")
            elif action == "minimize":
                pyautogui.hotkey("alt", "space")
                pyautogui.press("n")
            elif action == "close":
                pyautogui.hotkey("alt", "f4")
            else:
                logger.error(f"Unknown window action: {action}")
                return False

            logger.info(f"Window action performed: {action}")
            return True
        except Exception as e:
            logger.error(f"Failed to control window: {e}")
            return False

    def control_mouse(self, params):
        """Control mouse (move, click)"""
        try:
            if not PYAUTOGUI_AVAILABLE:
                logger.error("pyautogui is not available, mouse control not possible")
                return False

            action = params.get("action", "")
            if not action:
                logger.error("No mouse action specified")
                return False

            x = params.get("x")
            y = params.get("y")

            if action == "move" and x is not None and y is not None:
                pyautogui.moveTo(x, y)
            elif action == "click":
                if x is not None and y is not None:
                    pyautogui.click(x, y)
                else:
                    pyautogui.click()
            elif action == "right_click":
                if x is not None and y is not None:
                    pyautogui.rightClick(x, y)
                else:
                    pyautogui.rightClick()
            elif action == "double_click":
                if x is not None and y is not None:
                    pyautogui.doubleClick(x, y)
                else:
                    pyautogui.doubleClick()
            else:
                logger.error(f"Unknown mouse action: {action}")
                return False

            logger.info(f"Mouse action performed: {action}")
            return True
        except Exception as e:
            logger.error(f"Failed to control mouse: {e}")
            return False

    def toggle_setting(self, params):
        """Toggle system settings (night mode, airplane mode, etc.)"""
        try:
            setting = params.get("setting", "")
            if not setting:
                logger.error("No setting specified")
                return False

            if self.system == "Windows":
                if setting == "night_mode":
                    pyautogui.hotkey("win", "a")
                    time.sleep(0.5)
                    pyautogui.hotkey("win", "a")
                    logger.info("Night mode toggle attempted")
                    return True
                else:
                    logger.error(f"Unsupported setting: {setting}")
                    return False
            else:
                logger.error(f"Setting toggle not implemented for {self.system}")
                return False
        except Exception as e:
            logger.error(f"Failed to toggle setting: {e}")
            return False

    def run_powershell_command(self, params):
        """Execute a PowerShell command"""
        logger.debug(f"Executing PowerShell command: {params}")
        try:
            command = params.get("command", "")
            if not command:
                return False

            ps_command = (
                f'powershell.exe -NoProfile -NonInteractive -Command "{command}"'
            )

            process = subprocess.Popen(
                ps_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True
            )

            output, error = process.communicate()

            if process.returncode != 0:
                logger.error(f"PowerShell command failed: {error.decode()}")
                return False

            logger.debug(f"PowerShell output: {output.decode()}")
            return True

        except Exception as e:
            logger.error(f"Error executing PowerShell command: {e}")
            return False

    def execute_commands_with_delays(self, commands):
        """Execute a list of commands with their respective delays"""
        for cmd_data in commands:
            command = cmd_data.get("command", "")
            delay_ms = cmd_data.get("delay_ms", 0)
            if command:
                time.sleep(delay_ms / 1000.0)
                try:
                    subprocess.Popen(
                        command,
                        shell=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    logger.info(f"Executed command: {command}")
                except Exception as e:
                    logger.error(f"Failed to execute command '{command}': {e}")

    def execute_powershell_commands_with_delays(self, commands):
        """Execute a list of PowerShell commands with their respective delays"""
        for cmd_data in commands:
            command = cmd_data.get("command", "")
            delay_ms = cmd_data.get("delay_ms", 0)
            if command:
                time.sleep(delay_ms / 1000.0)
                try:
                    ps_command = f'powershell.exe -NoProfile -NonInteractive -Command "{command}"'
                    process = subprocess.Popen(
                        ps_command,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        shell=True,
                    )
                    output, error = process.communicate()
                    if process.returncode != 0:
                        logger.error(f"PowerShell command failed: {error.decode()}")
                    else:
                        logger.info(f"Executed PowerShell command: {command}")
                        logger.debug(f"PowerShell output: {output.decode()}")
                except Exception as e:
                    logger.error(
                        f"Failed to execute PowerShell command '{command}': {e}"
                    )

    def text_to_speech(self, params):
        """Play text-to-speech for selected text from clipboard"""
        try:
            logger.info("Text-to-speech action triggered")
            
            # Get parameters with defaults
            language = params.get("language", "auto")
            voice = params.get("voice", "auto")
            mood = params.get("mood", "neutral")
            frequency = params.get("frequency", "24000")
            text_source = params.get("text_source", "clipboard")
            
            # Create configuration
            tts_config = {
                "language": language,
                "voice": voice,
                "mood": mood,
                "frequency": frequency,
                "text_source": text_source
            }
            
            # Import the TTS manager here to avoid circular imports
            from app.text_to_speech import tts_manager
            
            # Play the text using the TTS manager
            result = tts_manager.play_text(tts_config)
            
            if result:
                self.notify("tts", "Text-to-speech playback started")
                return True
            else:
                self.notify("tts_error", "Failed to start text-to-speech playback")
                return False
                
        except Exception as e:
            logger.error(f"Error in text-to-speech action: {e}")
            self.notify("tts_error", f"Text-to-speech error: {str(e)}")
            return False

    def wake_on_lan(self, params):
        """
        Send a Wake-on-LAN magic packet to one or more MAC addresses
        
        Args:
            params (dict): Parameters containing:
                - mac_address (str): MAC address of the device to wake up
                - ip_address (str, optional): IP address to send to (default: 255.255.255.255)
                - port (int, optional): UDP port to use (default: 9)
        
        Returns:
            bool: True if the packet was sent successfully, False otherwise
        """
        try:
            # Get parameters
            mac_address = params.get("mac_address", "")
            ip_address = params.get("ip_address", "255.255.255.255")  # Default to broadcast
            port = params.get("port", 9)  # Default WoL port if not specified
            
            if not mac_address:
                logger.error("No MAC address specified for Wake-on-LAN")
                self.notify("error", "No MAC address specified for Wake-on-LAN")
                return False
                
            # Split by commas if multiple MAC addresses are provided
            mac_addresses = [addr.strip() for addr in mac_address.split(",") if addr.strip()]
            
            if not mac_addresses:
                logger.error("No valid MAC addresses found")
                self.notify("error", "No valid MAC addresses found")
                return False
                
            success = False
            valid_macs = []
            invalid_macs = []
            
            # Process each MAC address
            for mac in mac_addresses:
                # Validate MAC address format
                mac_pattern = re.compile(r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$')
                if not mac_pattern.match(mac):
                    logger.warning(f"Invalid MAC address format: {mac}")
                    invalid_macs.append(mac)
                    continue
                    
                valid_macs.append(mac)
                
                # Convert MAC address to bytes
                mac_bytes = bytearray.fromhex(mac.replace(":", "").replace("-", ""))
                
                # Create magic packet (6 bytes of 0xFF followed by MAC address repeated 16 times)
                magic_packet = b'\xff' * 6 + mac_bytes * 16
                
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                        s.sendto(magic_packet, (ip_address, port))
                    logger.info(f"Wake-on-LAN packet sent to {mac} (via {ip_address}:{port})")
                    success = True
                except Exception as e:
                    logger.error(f"Failed to send WoL packet to {mac}: {e}")
            
            # Build notification message
            if success:
                if len(valid_macs) == 1:
                    self.notify("wol", f"Wake-on-LAN packet sent to {valid_macs[0]}")
                else:
                    self.notify("wol", f"Wake-on-LAN packets sent to {len(valid_macs)} devices")
                    
                if invalid_macs:
                    logger.warning(f"Could not send to {len(invalid_macs)} invalid MAC addresses")
                    
                return True
            else:
                self.notify("error", "Failed to send any Wake-on-LAN packets")
                return False
            
        except Exception as e:
            error_msg = f"Error sending Wake-on-LAN packet: {e}"
            logger.error(error_msg)
            self.notify("error", error_msg)
            return False

    def control_webos_tv(self, params):
        """
        Control an LG WebOS TV device
        
        Args:
            params (dict): Parameters containing:
                - ip (str): IP address of the TV
                - command (str): Command to send to the TV
                - connect_only (bool, optional): Only connect without sending command
        
        Returns:
            bool: True if the command was sent successfully, False otherwise
        """
        try:
            if not WEBOS_AVAILABLE:
                logger.error("WebOS TV module is not available. Install aiowebostv with 'pip install aiowebostv'")
                self.notify("error", "WebOS TV module is not available")
                return False
                
            # Get parameters
            ip = params.get("ip", "")
            command = params.get("command", "")
            connect_only = params.get("connect_only", False)
            
            if not ip:
                logger.error("No IP address specified for WebOS TV control")
                self.notify("error", "No IP address specified for TV")
                return False
                
            # Create a new asyncio event loop in a separate thread for async operations
            result_event = threading.Event()
            result_container = {"success": False, "message": ""}
            
            def run_async_operation():
                async def async_operation():
                    try:
                        # Force a reconnection for each operation - more reliable than reusing connections
                        success = await webos_manager.force_reconnect(ip)
                        
                        if not success:
                            result_container["message"] = f"Failed to connect to TV at {ip}"
                            return False
                        
                        # If only connecting, we're done
                        if connect_only:
                            tv_name = webos_manager.config.get(ip, {}).get("name", f"LG TV ({ip})")
                            result_container["message"] = f"Connected to {tv_name}"
                            result_container["success"] = True
                            return True
                        
                        # Execute the command
                        if not command:
                            result_container["message"] = "No command specified"
                            return False
                        
                        # Execute the command directly
                        command_success = await webos_manager.execute_command(ip, command)
                        
                        if command_success:
                            # Try to get a friendly command description
                            cmd_desc = command
                            for cmd_name, cmd_info in webos_manager.default_commands.items():
                                if cmd_info["command"] == command:
                                    cmd_desc = cmd_info["description"]
                                    break
                                
                            result_container["message"] = f"Sent '{cmd_desc}' to TV"
                            result_container["success"] = True
                            return True
                        else:
                            result_container["message"] = f"Failed to send command '{command}' to TV"
                            return False
                    except Exception as e:
                        logger.error(f"Error in WebOS TV control: {str(e)}")
                        result_container["message"] = f"Error: {str(e)}"
                        return False
                    finally:
                        result_event.set()
                
                # Create and run the event loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(async_operation())
                finally:
                    loop.close()
            
            # Start the thread and wait for completion with timeout
            thread = threading.Thread(target=run_async_operation)
            thread.start()
            thread.join(timeout=10.0)  # Wait up to 10 seconds for the operation to complete
            
            if not result_event.is_set():
                logger.warning("WebOS TV operation timed out")
                self.notify("error", "TV operation timed out")
                return False
                
            if result_container["success"]:
                self.notify("webos_tv", result_container["message"])
                return True
            else:
                self.notify("error", result_container["message"])
                return False
                
        except Exception as e:
            error_msg = f"Error controlling WebOS TV: {e}"
            logger.error(error_msg)
            self.notify("error", error_msg)
            return False


def execute_shortcut(shortcut: str):
    """Executes a keyboard shortcut using pyautogui."""
    keys = shortcut.lower().split("+")
    logger.debug(f"Executing shortcut: {keys}")
    try:
        pyautogui.hotkey(*keys)
    except Exception as e:
        logger.error(f"Error executing shortcut: {e}")


def open_website(url: str):
    """Opens a website in the default web browser."""
    logger.debug(f"Opening website: {url}")
    try:
        webbrowser.open(url)
    except Exception as e:
        logger.error(f"Error opening website: {e}")


def open_app(path: str):
    """Opens a specified application."""
    logger.debug(f"Opening application: {path}")
    try:
        subprocess.Popen(path)
    except FileNotFoundError:
        logger.error(f"Application not found: {path}")
    except Exception as e:
        logger.error(f"Error opening application: {e}")


def set_volume(volume_level: int):
    """Sets the system volume."""
    logger.debug(f"Setting volume to: {volume_level}")
    try:
        if has_pycaw:
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = interface.QueryInterface(IAudioEndpointVolume)
            scalar_volume = volume_level / 100.0
            volume.SetMasterVolumeLevelScalar(scalar_volume, None)
            logger.info("Volume set using pycaw")
        else:
            # Fallback to PowerShell if pycaw is not available
            powershell_command = f"$volume = {volume_level}; $WshShell = New-Object -ComObject WScript.Shell; $WshShell.SendKeys([char]174)"
            subprocess.run(["powershell", "-Command", powershell_command])
            logger.info("Volume set using SendKeys method")
    except Exception as e:
        logger.error(f"Error setting volume: {e}")


def switch_audio_device(device_name: Optional[str] = None):
    """Switches to the specified audio device, or toggles if no device is specified."""
    logger.debug(f"Switching audio device to: {device_name}")
    try:
        if device_name:
            # Switch to the specified device
            powershell_command = f"Set-AudioDevice -DeviceName '{device_name}'"
        else:
            # Toggle between available devices
            powershell_command = "Toggle-AudioDevice"
        subprocess.run(["powershell", "-Command", powershell_command])
        logger.info("Audio device switched using PowerShell")
    except Exception as e:
        logger.error(f"Error switching audio device: {e}")


def send_media_control(control: str):
    """Sends a media control command (play/pause, next, previous)."""
    logger.debug(f"Sending media control: {control}")
    try:
        if has_pycaw:
            # Use pycaw for media control
            if control == "play_pause":
                pyautogui.press("playpause")
            elif control == "next_track":
                pyautogui.press("nexttrack")
            elif control == "previous_track" or control == "prev_track":
                pyautogui.press("prevtrack")
            logger.info("Media control sent using pycaw/pyautogui")
        else:
            # Fallback to SendKeys if pycaw is not available
            if control == "play_pause":
                powershell_command = "$WshShell = New-Object -ComObject WScript.Shell; $WshShell.SendKeys([char]179)"  # '{PlayPause}'"
                # powershell_command = "$WshShell = New-Object -ComObject WScript.Shell; $WshShell.SendKeys('{MEDIA_PLAY_PAUSE}')"
            elif control == "next_track":
                powershell_command = "$WshShell = New-Object -ComObject WScript.Shell; $WshShell.SendKeys([char]176)"  # '{NextTrack}'"
            # powershell_command = "$WshShell = New-Object -ComObject WScript.Shell; $WshShell.SendKeys('{MEDIA_NEXT_TRACK}')"
            elif control == "previous_track" or control == "prev_track":
                powershell_command = "$WshShell = New-Object -ComObject WScript.Shell; $WshShell.SendKeys([char]177)"  # '{PrevTrack}'"
                # powershell_command = "$WshShell = New-Object -ComObject WScript.Shell; $WshShell.SendKeys('{MEDIA_PREV_TRACK}')"
            else:
                logger.warning(f"Unsupported media control: {control}")
                return

            subprocess.run(["powershell", "-Command", powershell_command])
            logger.info("Media control sent using SendKeys method")

    except Exception as e:
        logger.error(f"Error sending media control: {e}")


def standardize_media_control(control: str) -> str:
    """Standardizes media control strings to a consistent format (lowercase, underscore)."""
    control = control.lower().replace(" ", "_")
    logger.debug(f"Standardized media control: {control}")
    return control


def execute_action(action_type: str, params: dict):
    """Executes the specified action with the given parameters."""
    logger.debug(f"Executing action: {action_type} with params: {params}")

    if action_type == "open_app":
        open_app(params["path"])
    elif action_type == "open_website":
        open_website(params["url"])
    elif action_type == "audio_device":
        switch_audio_device(params.get("device_name"))
    elif action_type == "shortcut":
        execute_shortcut(params["shortcut"])
    elif action_type == "media":
        control = standardize_media_control(params["control"])
        send_media_control(control)
    else:
        logger.warning(f"Unknown action type: {action_type}")
