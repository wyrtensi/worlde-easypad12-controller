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

    def switch_audio_device(self, device_name=None):
        """Switch between audio output devices"""
        try:
            if self.system == "Windows":
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
                logger.debug(
                    f"Audio device switching requested for device: '{device_name}'"
                )
                result = self.switch_audio_device(device_name)
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

            logger.info(f"Typing text: {text[:20]}...")
            
            # Primary method: use pyautogui's write function
            try:
                pyautogui.write(text)
                return True
            except Exception as e:
                logger.warning(f"Failed to type text directly with pyautogui: {e}, trying clipboard method")
                
            # Method 0: Direct Windows clipboard API (most reliable on Windows)
            if WIN32CLIPBOARD_AVAILABLE and self.system == "Windows":
                try:
                    logger.info("Attempting to use direct Win32 clipboard API")
                    
                    # Save original clipboard content
                    original_clipboard_data = None
                    win32clipboard.OpenClipboard()
                    if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                        original_clipboard_data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                    win32clipboard.EmptyClipboard()
                    
                    # Set new clipboard content
                    win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
                    win32clipboard.CloseClipboard()
                    
                    time.sleep(0.5)  # Increased time for clipboard to register
                    
                    # Try to paste using keybd_event for most reliable input (similar to ask_chatgpt)
                    try:
                        # Define the input constants
                        KEYEVENTF_KEYDOWN = 0x0000
                        KEYEVENTF_KEYUP = 0x0002
                        
                        # More reliable direct Windows API approach
                        ctypes.windll.user32.keybd_event(0x11, 0, KEYEVENTF_KEYDOWN, 0)  # Ctrl down
                        time.sleep(0.05)
                        ctypes.windll.user32.keybd_event(0x56, 0, KEYEVENTF_KEYDOWN, 0)  # V down
                        time.sleep(0.05)
                        ctypes.windll.user32.keybd_event(0x56, 0, KEYEVENTF_KEYUP, 0)    # V up
                        time.sleep(0.05)
                        ctypes.windll.user32.keybd_event(0x11, 0, KEYEVENTF_KEYUP, 0)    # Ctrl up
                        
                        time.sleep(0.3)
                        logger.info("Pasted using direct keybd_event Windows API")
                        
                        # Restore original clipboard
                        time.sleep(0.5)  # Increased delay before restoring clipboard
                        win32clipboard.OpenClipboard()
                        win32clipboard.EmptyClipboard()
                        if original_clipboard_data:
                            win32clipboard.SetClipboardText(original_clipboard_data, win32con.CF_UNICODETEXT)
                        win32clipboard.CloseClipboard()
                        
                        return True
                    except Exception as win32_err:
                        logger.warning(f"keybd_event failed: {win32_err}, trying another method")
                    
                    # Try SendInput method if keybd_event failed
                    try:
                        # Import necessary ctypes structures
                        from ctypes import Structure, c_ulong, c_ushort, POINTER, sizeof, byref
                        
                        class KeyboardInput(Structure):
                            _fields_ = [
                                ("wVk", c_ushort),
                                ("wScan", c_ushort),
                                ("dwFlags", c_ulong),
                                ("time", c_ulong),
                                ("dwExtraInfo", POINTER(c_ulong))
                            ]
                        
                        class HardwareInput(Structure):
                            _fields_ = [
                                ("uMsg", c_ulong),
                                ("wParamL", c_ushort),
                                ("wParamH", c_ushort)
                            ]
                        
                        class MouseInput(Structure):
                            _fields_ = [
                                ("dx", c_ulong),
                                ("dy", c_ulong),
                                ("mouseData", c_ulong),
                                ("dwFlags", c_ulong),
                                ("time", c_ulong),
                                ("dwExtraInfo", POINTER(c_ulong))
                            ]
                        
                        class InputUnion(ctypes.Union):
                            _fields_ = [
                                ("ki", KeyboardInput),
                                ("mi", MouseInput),
                                ("hi", HardwareInput)
                            ]
                        
                        class Input(Structure):
                            _fields_ = [
                                ("type", c_ulong),
                                ("ii", InputUnion)
                            ]
                        
                        # Create input array for Ctrl+V sequence
                        inputs = (Input * 4)()
                        
                        # VK_CONTROL down
                        inputs[0].type = 1  # INPUT_KEYBOARD
                        inputs[0].ii.ki.wVk = 0x11  # VK_CONTROL
                        inputs[0].ii.ki.dwFlags = KEYEVENTF_KEYDOWN
                        
                        # V key down
                        inputs[1].type = 1  # INPUT_KEYBOARD
                        inputs[1].ii.ki.wVk = 0x56  # V key
                        inputs[1].ii.ki.dwFlags = KEYEVENTF_KEYDOWN
                        
                        # V key up
                        inputs[2].type = 1  # INPUT_KEYBOARD
                        inputs[2].ii.ki.wVk = 0x56  # V key
                        inputs[2].ii.ki.dwFlags = KEYEVENTF_KEYUP
                        
                        # VK_CONTROL up
                        inputs[3].type = 1  # INPUT_KEYBOARD
                        inputs[3].ii.ki.wVk = 0x11  # VK_CONTROL
                        inputs[3].ii.ki.dwFlags = KEYEVENTF_KEYUP
                        
                        # Send input
                        ctypes.windll.user32.SendInput(4, byref(inputs), sizeof(Input))
                        time.sleep(0.3)
                        logger.info("Pasted using direct SendInput Windows API")
                        
                        # Restore original clipboard
                        time.sleep(0.5)  # Increased delay
                        win32clipboard.OpenClipboard()
                        win32clipboard.EmptyClipboard()
                        if original_clipboard_data:
                            win32clipboard.SetClipboardText(original_clipboard_data, win32con.CF_UNICODETEXT)
                        win32clipboard.CloseClipboard()
                        
                        return True
                    except Exception as win32_err:
                        logger.warning(f"SendInput failed: {win32_err}, trying fallback paste method")
                        
                    # Try another Windows-specific method with UI Automation
                    try:
                        # Use Windows UI Automation API to paste if available
                        cmd = 'powershell -command "$wshell = New-Object -ComObject wscript.shell; $wshell.SendKeys(\'^v\')"'
                        subprocess.run(cmd, shell=True, capture_output=True)
                        time.sleep(0.3)
                        logger.info("Pasted with PowerShell SendKeys")
                        
                        # Restore original clipboard
                        time.sleep(0.5)  # Increased delay
                        win32clipboard.OpenClipboard()
                        win32clipboard.EmptyClipboard()
                        if original_clipboard_data:
                            win32clipboard.SetClipboardText(original_clipboard_data, win32con.CF_UNICODETEXT)
                        win32clipboard.CloseClipboard()
                        
                        return True
                    except Exception as automation_err:
                        logger.warning(f"PowerShell SendKeys paste failed: {automation_err}")
                        
                    # At this point we'll continue with other methods but with the
                    # text already in clipboard from the win32clipboard API
                        
                except Exception as win32_err:
                    logger.warning(f"Direct Win32 clipboard method failed: {win32_err}")
                    # Continue to other methods
            
            # Fallback method 1: Use clipboard for longer or complex text
            if PYPERCLIP_AVAILABLE:
                try:
                    # Save original clipboard content
                    try:
                        original_clipboard = pyperclip.paste()
                    except Exception as clip_err:
                        logger.warning(f"Failed to get original clipboard: {clip_err}")
                        original_clipboard = ""
                    
                    # Try multiple ways to copy text to clipboard
                    copy_success = False
                    try:
                        pyperclip.copy(text)
                        time.sleep(0.5)  # Increased wait time for clipboard
                        copy_success = True
                    except Exception as copy_err:
                        logger.warning(f"pyperclip copy failed: {copy_err}")
                    
                    # Verify clipboard content
                    try:
                        clipboard_content = pyperclip.paste()
                        if clipboard_content != text:
                            logger.warning(f"Clipboard verification failed. Expected: {text[:20]}..., Got: {clipboard_content[:20]}...")
                        else:
                            logger.debug("Clipboard content verified successfully")
                    except Exception as verify_err:
                        logger.warning(f"Failed to verify clipboard: {verify_err}")
                    
                    # Try multiple paste methods
                    paste_success = False
                    
                    # Method 1: pyautogui paste
                    if not paste_success:
                        try:
                            # Try with small delay between key presses
                            pyautogui.keyDown('ctrl')
                            time.sleep(0.1)
                            pyautogui.press('v')
                            time.sleep(0.1)
                            pyautogui.keyUp('ctrl')
                            time.sleep(0.3)
                            paste_success = True
                            logger.info("Pasted text using pyautogui keyDown/keyUp method")
                        except Exception as paste_err1:
                            logger.warning(f"pyautogui keyDown/keyUp paste failed: {paste_err1}")
                    
                    # Method 2: pyautogui hotkey
                    if not paste_success:
                        try:
                            pyautogui.hotkey('ctrl', 'v')
                            time.sleep(0.3)
                            paste_success = True
                            logger.info("Pasted text using pyautogui hotkey method")
                        except Exception as paste_err2:
                            logger.warning(f"pyautogui hotkey paste failed: {paste_err2}")
                    
                    # Method 3: keyboard module
                    if not paste_success and KEYBOARD_AVAILABLE:
                        try:
                            keyboard.press_and_release('ctrl+v')
                            time.sleep(0.3)
                            paste_success = True
                            logger.info("Pasted text using keyboard module")
                        except Exception as kb_err:
                            logger.warning(f"keyboard module paste failed: {kb_err}")
                    
                    # Method 4: Windows-specific SendKeys via PowerShell
                    if not paste_success and self.system == "Windows":
                        try:
                            cmd = 'powershell -command "$wshell = New-Object -ComObject wscript.shell; $wshell.SendKeys(\'^v\')"'
                            subprocess.run(cmd, shell=True)
                            time.sleep(0.5)
                            paste_success = True
                            logger.info("Pasted text using PowerShell SendKeys")
                        except Exception as ps_err:
                            logger.warning(f"PowerShell SendKeys paste failed: {ps_err}")
                    
                    # Restore original clipboard after a delay
                    time.sleep(0.5)
                    try:
                        pyperclip.copy(original_clipboard)
                    except Exception as restore_err:
                        logger.warning(f"Failed to restore clipboard: {restore_err}")
                    
                    if paste_success:
                        return True
                        
                except Exception as clip_err:
                    logger.warning(f"Clipboard fallback method failed: {clip_err}")
            else:
                logger.warning("pyperclip not available for clipboard fallback")
            
            # Fallback method 2: Type character by character with delay
            try:
                for char in text:
                    pyautogui.write(char)
                    time.sleep(0.01)  # Small delay between characters
                return True
            except Exception as char_err:
                logger.error(f"Character-by-character typing failed: {char_err}")
                
            logger.error("All typing methods failed")
            return False
            
        except Exception as e:
            logger.error(f"Failed to type text: {e}")
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
