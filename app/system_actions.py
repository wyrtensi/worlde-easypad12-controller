import subprocess
import webbrowser
import os
import ctypes
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL
import json
import logging
from app.utils import ensure_app_directories, save_button_config, get_saved_button_configs
import platform
import sys
import time
import importlib.util
from typing import Optional

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

logger = logging.getLogger('midi_keyboard.system')

# Check if pycaw is installed
pycaw_spec = importlib.util.find_spec("comtypes")
if pycaw_spec is not None:
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    has_pycaw = True
else:
    has_pycaw = False

class SystemActions:
    def __init__(self):
        """Initialize the system actions handler"""
        self.system = platform.system()  # Windows, Darwin (macOS), or Linux
        logger.info(f"Initializing SystemActions for {self.system}")
        
        # Ensure config directories exist
        config_dir, logs_dir = ensure_app_directories()
        
        # Path for saved button configurations
        self.config_path = os.path.join(config_dir, "button_config.json")
        
        # Load existing configurations if available
        self.button_configs = self.load_button_configs()
        
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
                    IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
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
    
    def __del__(self):
        """Clean up resources when the object is destroyed"""
        # We don't need to explicitly uninitialize COM with pywin32
    
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
    
    def open_website(self, action_params):
        """Open a website in the default browser
        
        Args:
            action_params (dict): Dictionary containing 'url' key
        
        Returns:
            bool: True if successful, False otherwise
        """
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
            webbrowser.open(url, new=2)  # new=2 means open in a new tab if possible
            return True
        except Exception as e:
            logger.error(f"Error opening website: {e}")
            return False
    
    def set_volume(self, action, value=None):
        """Adjust system volume
        
        Args:
            action (str): Action to perform (increase, decrease, mute, unmute, set)
            value (int, optional): Value to set (0-100) if action is 'set'
            
        Returns:
            bool: True if volume control successful, False otherwise
        """
        try:
            if self.system == "Windows":
                # First try pycaw if available
                if self.pycaw_available and self.com_initialized and self.volume:
                    try:
                        # Re-initialize COM if needed
                        import win32com.client
                        if not self.com_initialized:
                            win32com.client.Dispatch("SAPI.SpVoice")
                            self.com_initialized = True
                            
                        current_vol = self.volume.GetMasterVolumeLevelScalar() * 100
                        logger.debug(f"Current volume: {current_vol:.0f}%")
                        
                        if action == "increase":
                            new_vol = min(current_vol + 5, 100) / 100
                            self.volume.SetMasterVolumeLevelScalar(new_vol, None)
                        elif action == "decrease":
                            new_vol = max(current_vol - 5, 0) / 100
                            self.volume.SetMasterVolumeLevelScalar(new_vol, None)
                        elif action == "mute":
                            self.volume.SetMute(1, None)
                        elif action == "unmute":
                            self.volume.SetMute(0, None)
                        elif action == "set" and value is not None:
                            new_vol = max(0, min(int(value), 100)) / 100
                            self.volume.SetMasterVolumeLevelScalar(new_vol, None)
                        else:
                            logger.warning(f"Unknown volume action: {action}")
                            return False
                        
                        logger.info(f"Volume {action} successful")
                        return True
                    except Exception as e:
                        logger.error(f"Failed to control volume with pycaw: {e}")
                        # Fall through to PowerShell method
                
                # Fall back to PowerShell method
                try:
                    if action == "increase":
                        os.system('powershell "(New-Object -ComObject WScript.Shell).SendKeys([char]175)"')
                    elif action == "decrease":
                        os.system('powershell "(New-Object -ComObject WScript.Shell).SendKeys([char]174)"')
                    elif action == "mute":
                        os.system('powershell "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"')
                    elif action == "set" and value is not None:
                        # Can't set exact volume with SendKeys, just adjust relative to current
                        current_vol_estimate = 50  # Estimate current volume
                        steps = abs(value - current_vol_estimate) // 2
                        key = '[char]175' if value > current_vol_estimate else '[char]174'
                        # Use multiple steps to get closer to desired volume
                        for _ in range(steps):
                            os.system(f'powershell "(New-Object -ComObject WScript.Shell).SendKeys({key})"')
                            
                        logger.info(f"Volume set with PowerShell successful")
                        return True
                    else:
                        logger.warning(f"Unknown volume action for PowerShell fallback: {action}")
                        return False
                        
                    logger.info(f"Volume {action} with PowerShell successful")
                    return True
                except Exception as fallback_err:
                    logger.error(f"PowerShell volume control failed: {fallback_err}")
                    return False
            elif self.system == "Darwin":  # macOS
                try:
                    if action == "increase":
                        os.system("osascript -e 'set volume output volume (output volume of (get volume settings) + 5)'")
                    elif action == "decrease":
                        os.system("osascript -e 'set volume output volume (output volume of (get volume settings) - 5)'")
                    elif action == "mute":
                        os.system("osascript -e 'set volume output muted true'")
                    elif action == "unmute":
                        os.system("osascript -e 'set volume output muted false'")
                    elif action == "set" and value is not None:
                        os.system(f"osascript -e 'set volume output volume {value}'")
                    else:
                        logger.warning(f"Unknown volume action: {action}")
                        return False
                    
                    logger.info(f"Volume {action} successful on macOS")
                    return True
                except Exception as mac_err:
                    logger.error(f"Failed to control volume on macOS: {mac_err}")
                    return False
                
            else:  # Linux
                try:
                    if action == "increase":
                        os.system("amixer -D pulse sset Master 5%+")
                    elif action == "decrease":
                        os.system("amixer -D pulse sset Master 5%-")
                    elif action == "mute":
                        os.system("amixer -D pulse sset Master mute")
                    elif action == "unmute":
                        os.system("amixer -D pulse sset Master unmute")
                    elif action == "set" and value is not None:
                        os.system(f"amixer -D pulse sset Master {value}%")
                    else:
                        logger.warning(f"Unknown volume action: {action}")
                        return False
                        
                    logger.info(f"Volume {action} successful on Linux")
                    return True
                except Exception as linux_err:
                    logger.error(f"Failed to control volume on Linux: {linux_err}")
                    return False
                
        except Exception as e:
            logger.error(f"Failed to control volume: {e}")
            return False
    
    def switch_audio_device(self, device_name=None):
        """Switch between audio output devices
        
        If a device name is provided, switch to that device specifically.
        If no device name is provided, toggle between available devices.
        
        Args:
            device_name (str, optional): Name of the audio device to switch to
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if self.system == "Windows":
                logger.debug(f"Attempting to switch audio device: '{device_name}'")
                
                # Only use AudioDeviceCmdlets for audio device switching
                try:
                    # First check if the module is available
                    cmd = 'powershell "Get-Command -Module AudioDeviceCmdlets -ErrorAction SilentlyContinue | Measure-Object | Select-Object -ExpandProperty Count"'
                    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                    
                    if result.returncode == 0 and result.stdout.strip() and int(result.stdout.strip()) > 0:
                        logger.info("AudioDeviceCmdlets module is available")
                        
                        if device_name:
                            # Try to find the device ID by partial name match
                            escaped_name = device_name.replace("'", "''")
                            cmd = f'powershell -Command "Get-AudioDevice -List | Where-Object {{$_.Type -eq \'Playback\' -and $_.Name -like \'*{escaped_name}*\'}} | Select-Object -ExpandProperty ID -First 1"'
                            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                            
                            if result.returncode == 0 and result.stdout.strip():
                                device_id = result.stdout.strip()
                                logger.debug(f"Found device ID: {device_id}")
                                
                                # Switch using ID instead of name
                                cmd = f'powershell -Command "Set-AudioDevice -ID \'{device_id}\'"'
                                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                                
                                if result.returncode == 0:
                                    logger.info(f"Successfully switched to audio device with ID: {device_id}")
                                    return True
                                else:
                                    logger.warning(f"Failed to switch using device ID: {result.stderr}")
                            else:
                                logger.warning(f"Could not find device ID for name: {device_name}")
                                logger.info("Opening Sound Control Panel as fallback")
                                subprocess.run('powershell "Start-Process control.exe -ArgumentList \'mmsys.cpl\'"', shell=True)
                                return True
                        else:
                            # Get all playback devices with their IDs
                            cmd = 'powershell -Command "Get-AudioDevice -List | Where-Object {$_.Type -eq \'Playback\'} | Select-Object -Property ID,Name | ConvertTo-Json -Compress"'
                            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                            
                            if result.returncode == 0 and result.stdout.strip():
                                try:
                                    # Parse the JSON response to get device info
                                    devices_json = json.loads(result.stdout)
                                    
                                    # Handle the case where we get a single device vs. multiple devices
                                    if isinstance(devices_json, dict):
                                        # Single device
                                        devices = [devices_json]
                                    else:
                                        # Multiple devices
                                        devices = devices_json
                                    
                                    device_ids = [device.get('ID') for device in devices]
                                    device_names = [device.get('Name') for device in devices]
                                    
                                    logger.debug(f"Available audio devices: {device_names}")
                                    
                                    if not device_ids or len(device_ids) <= 1:
                                        logger.info("Only one or no audio devices found, no need to switch")
                                        return True
                                    
                                    # Get current active device ID
                                    cmd = 'powershell -Command "Get-AudioDevice -Playback | Select-Object -ExpandProperty ID"'
                                    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                                    
                                    if result.returncode == 0 and result.stdout.strip():
                                        current_device_id = result.stdout.strip()
                                        
                                        # Get the name for logging
                                        cmd_name = 'powershell -Command "Get-AudioDevice -Playback | Select-Object -ExpandProperty Name"'
                                        result_name = subprocess.run(cmd_name, shell=True, capture_output=True, text=True)
                                        current_device = result_name.stdout.strip() if result_name.returncode == 0 else "Unknown"
                                        
                                        logger.debug(f"Current active device: {current_device}")
                                        
                                        try:
                                            # Check if current device ID is in our list
                                            if current_device_id in device_ids:
                                                current_index = device_ids.index(current_device_id)
                                                # Get the next device (cycle back to start if at the end)
                                                next_index = (current_index + 1) % len(device_ids)
                                                next_device_id = device_ids[next_index]
                                                next_device_name = device_names[next_index] if next_index < len(device_names) else "Unknown"
                                                
                                                logger.debug(f"Switching from device index {current_index} to index {next_index}")
                                                logger.info(f"Switching from '{current_device}' to '{next_device_name}'")
                                                
                                                # Set next device as active using ID
                                                cmd = f'powershell -Command "Set-AudioDevice -ID \'{next_device_id}\'"'
                                                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                                                
                                                if result.returncode == 0:
                                                    # Verify the switch happened
                                                    time.sleep(0.5)  # Give system time to change
                                                    cmd_verify = 'powershell -Command "Get-AudioDevice -Playback | Select-Object -ExpandProperty ID"'
                                                    result_verify = subprocess.run(cmd_verify, shell=True, capture_output=True, text=True)
                                                    
                                                    if result_verify.returncode == 0 and result_verify.stdout.strip() == next_device_id:
                                                        logger.info(f"Verified switch to audio device: {next_device_name}")
                                                        return True
                                                    else:
                                                        logger.warning("Device switch command succeeded but verification failed")
                                                        # Try alternative method
                                                        cmd_alt = f'powershell -Command "$device = Get-AudioDevice -List | Where-Object {{$_.ID -eq \'{next_device_id}\'}}; $device | Set-AudioDevice"'
                                                        result_alt = subprocess.run(cmd_alt, shell=True, capture_output=True, text=True)
                                                        
                                                        if result_alt.returncode == 0:
                                                            logger.info("Successfully switched using alternative method")
                                                            return True
                                                else:
                                                    logger.warning(f"Failed to switch device using ID: {result.stderr}")
                                            else:
                                                logger.warning(f"Current device ID '{current_device_id}' not found in device list")
                                                # Just switch to the first device in the list
                                                next_device_id = device_ids[0]
                                                next_device_name = device_names[0] if len(device_names) > 0 else "Unknown"
                                                
                                                logger.info(f"Switching to first available device: '{next_device_name}'")
                                                cmd = f'powershell -Command "Set-AudioDevice -ID \'{next_device_id}\'"'
                                                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                                                
                                                if result.returncode == 0:
                                                    logger.info(f"Successfully switched to audio device: {next_device_name}")
                                                    return True
                                        except Exception as e:
                                            logger.error(f"Error during device switching: {e}")
                                    else:
                                        logger.warning("Failed to get current audio device")
                                except Exception as e:
                                    logger.error(f"Error parsing device information: {e}")
                            else:
                                logger.warning("Failed to get available audio devices")
                    else:
                        logger.warning("AudioDeviceCmdlets module is not available")
                        # Open the Windows sound settings dialog as fallback
                        subprocess.run('powershell "Start-Process control.exe -ArgumentList \'mmsys.cpl\'"', shell=True)
                        logger.info("Opened Windows Sound Control Panel")
                        return True
                except Exception as e:
                    logger.error(f"Error using AudioDeviceCmdlets: {e}")
                
                # Final fallback: open Sound Control Panel
                logger.info("Using fallback method: Opening Sound Control Panel")
                subprocess.run('powershell "Start-Process control.exe -ArgumentList \'mmsys.cpl\'"', shell=True)
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
        """Send a keyboard shortcut combination
        
        Args:
            shortcut (str): Keyboard shortcut string (e.g., "ctrl+c", "alt+tab", "win+r")
            
        Returns:
            bool: True if the shortcut was sent successfully, False otherwise
        """
        if not shortcut:
            logger.error("No shortcut specified")
            return False
        
        try:
            if not PYAUTOGUI_AVAILABLE:
                logger.error("pyautogui is not available, keyboard shortcuts cannot be sent")
                return False
                
            logger.info(f"Sending keyboard shortcut: {shortcut}")
            
            # Replace common key names for compatibility with pyautogui
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
                "numlock": "numlock"
            }
            
            # Handle function keys
            for i in range(1, 13):
                key_mapping[f"f{i}"] = f"f{i}"
            
            # Split the shortcut string and normalize keys
            keys = [k.strip().lower() for k in shortcut.split('+')]
            normalized_keys = []
            
            for key in keys:
                # Look up the key in our mapping or use as-is
                normalized_key = key_mapping.get(key, key)
                normalized_keys.append(normalized_key)
                
            # Use pyautogui to execute the shortcut
            pyautogui.hotkey(*normalized_keys)
            logger.info(f"Keyboard shortcut sent: {shortcut}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send keyboard shortcut: {e}")
            return False
    
    def media_control(self, control):
        """Control media playback (play/pause, next, previous, etc.)
        
        Args:
            control (str): Control action to perform (play_pause, next, previous, etc.)
            
        Returns:
            bool: True if media control successful, False otherwise
        """
        try:
            if self.system == "Windows":
                # Map the control to standardized control names
                # 'next' and 'previous' might be coming from older configs
                control_map = {
                    "next": "next_track",
                    "previous": "prev_track",
                    "next_track": "next_track",
                    "prev_track": "prev_track",
                    "previous_track": "prev_track",
                    "mute": "volume_mute",
                    "volume_mute": "volume_mute",
                }
                
                # Get standardized control name if it exists
                control = control_map.get(control, control)
                logger.debug(f"Standardized media control: {control}")
                
                # First try using pyautogui
                if PYAUTOGUI_AVAILABLE:
                    try:
                        logger.debug("Attempting media control with pyautogui")
                        if control == "play_pause":
                            pyautogui.press("playpause")
                            logger.info("Play/pause sent using pyautogui")
                            return True
                            
                        elif control == "next_track":
                            pyautogui.press("nexttrack")
                            logger.info("Next track sent using pyautogui")
                            return True
                            
                        elif control == "prev_track":
                            pyautogui.press("prevtrack")
                            logger.info("Previous track sent using pyautogui")
                            return True
                            
                        elif control == "stop":
                            pyautogui.press("stop")
                            logger.info("Stop sent using pyautogui")
                            return True
                            
                        elif control == "volume_up":
                            pyautogui.press("volumeup")
                            logger.info("Volume up sent using pyautogui")
                            return True
                            
                        elif control == "volume_down":
                            pyautogui.press("volumedown")
                            logger.info("Volume down sent using pyautogui")
                            return True
                            
                        elif control == "volume_mute":
                            pyautogui.press("volumemute")
                            logger.info("Mute toggle sent using pyautogui")
                            return True
                    except Exception as e:
                        logger.error(f"Failed to send media control via pyautogui: {e}")
                        # Fall through to the next method
                
                # If pyautogui fails, try SendKeys
                try:
                    if control == "play_pause":
                        os.system('powershell "(New-Object -ComObject WScript.Shell).SendKeys([char]179)"') # Try [char]179
                        #os.system('powershell "(New-Object -ComObject WScript.Shell).SendKeys([char]249)"') # Try [char]249
                        #os.system('powershell "(New-Object -ComObject WScript.Shell).SendKeys([char]255)"') # Try [char]255
                        logger.info("Play/pause sent using SendKeys method")
                        return True
                        
                    elif control == "next_track":
                        os.system('powershell "(New-Object -ComObject WScript.Shell).SendKeys([char]176)"')
                        logger.info("Next track sent using SendKeys method")
                        return True
                        
                    elif control == "prev_track":
                        os.system('powershell "(New-Object -ComObject WScript.Shell).SendKeys([char]177)"')
                        logger.info("Previous track sent using SendKeys method")
                        return True
                        
                    elif control == "stop":
                        os.system('powershell "(New-Object -ComObject WScript.Shell).SendKeys([char]178)"')
                        logger.info("Stop sent using SendKeys method")
                        return True
                        
                    elif control == "volume_up":
                        os.system('powershell "(New-Object -ComObject WScript.Shell).SendKeys([char]175)"')
                        logger.info("Volume up sent using SendKeys method")
                        return True
                        
                    elif control == "volume_down":
                        os.system('powershell "(New-Object -ComObject WScript.Shell).SendKeys([char]174)"')
                        logger.info("Volume down sent using SendKeys method")
                        return True
                        
                    elif control == "volume_mute":
                        os.system('powershell "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"')
                        logger.info("Mute toggle sent using SendKeys method")
                        return True
                    
                    else:
                        logger.warning(f"Unknown media control: {control}")
                        # Fall through to next method
                except Exception as e:
                    logger.error(f"Failed to send media control via SendKeys: {e}")
                    # Fall through to next method
                
                # Last fallback method - direct keyboard key codes
                try:
                    import keyboard
                    
                    if control == "play_pause":
                        keyboard.press_and_release("play/pause media")
                        logger.info("Play/pause sent using keyboard library")
                        return True
                        
                    elif control == "next_track":
                        keyboard.press_and_release("next track")
                        logger.info("Next track sent using keyboard library")
                        return True
                        
                    elif control == "prev_track":
                        keyboard.press_and_release("previous track")
                        logger.info("Previous track sent using keyboard library")
                        return True
                        
                    elif control == "stop":
                        keyboard.press_and_release("stop media")
                        logger.info("Stop sent using keyboard library")
                        return True
                        
                    elif control == "volume_up":
                        keyboard.press_and_release("volume up")
                        logger.info("Volume up sent using keyboard library")
                        return True
                        
                    elif control == "volume_down":
                        keyboard.press_and_release("volume down")
                        logger.info("Volume down sent using keyboard library")
                        return True
                        
                    elif control == "volume_mute":
                        keyboard.press_and_release("volume mute")
                        logger.info("Mute toggle sent using keyboard library")
                        return True
                        
                except (ImportError, Exception) as e:
                    logger.error(f"Failed to send media control with keyboard library: {e}")
                    return False
                
            elif self.system == "Darwin":  # macOS
                if control == "play_pause":
                    os.system("osascript -e 'tell application \"System Events\" to key code 16 using {command down}'")
                elif control == "next":
                    os.system("osascript -e 'tell application \"System Events\" to key code 17 using {command down}'")
                elif control == "previous":
                    os.system("osascript -e 'tell application \"System Events\" to key code 18 using {command down}'")
                else:
                    logger.warning(f"Unsupported media control on macOS: {control}")
                    return False
                    
            else:  # Linux
                if control == "play_pause":
                    os.system("dbus-send --print-reply --dest=org.mpris.MediaPlayer2.spotify /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Player.PlayPause")
                elif control == "next":
                    os.system("dbus-send --print-reply --dest=org.mpris.MediaPlayer2.spotify /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Player.Next")
                elif control == "previous":
                    os.system("dbus-send --print-reply --dest=org.mpris.MediaPlayer2.spotify /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Player.Previous")
                else:
                    logger.warning(f"Unsupported media control on Linux: {control}")
                    return False
            
            logger.info(f"Media control {control} successful")
            return True
            
        except Exception as e:
            logger.error(f"Failed to control media: {e}")
            return False
    
    def save_button_config(self, button_id, action_type, action_data, name=None, enabled=True):
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
            # Use the utility function that loads all individual button config files
            configs = get_saved_button_configs()
            if configs:
                logger.info(f"Loaded {len(configs)} button configurations")
                return configs
            
            # For backward compatibility, try the old method (single JSON file)
            if os.path.exists(self.config_path):
                try:
                    with open(self.config_path, 'r') as f:
                        old_configs = json.load(f)
                    logger.info(f"Loaded {len(old_configs)} button configurations from legacy file")
                    return old_configs
                except Exception as e:
                    logger.error(f"Error loading button configurations from legacy file: {e}")
            
            logger.info("No saved button configurations found")
            return {}
        except Exception as e:
            logger.error(f"Error in load_button_configs: {e}")
            return {}
    
    def execute_action(self, action_type, action_params):
        """Execute the specified action with the given parameters
        
        Args:
            action_type (str): Type of action to execute (app, web, volume, etc.)
            action_params (dict): Parameters for the action
        
        Returns:
            bool: True if the action was executed successfully, False otherwise
        """
        logger.debug(f"Executing action: {action_type} with params: {action_params}")
        
        try:
            # Convert params to dict if it's a string
            if isinstance(action_params, str):
                try:
                    action_params = json.loads(action_params)
                except json.JSONDecodeError:
                    # If not a valid JSON, treat as a simple string parameter
                    action_params = {"value": action_params}
            
            # Ensure action_params is a dictionary
            if action_params is None:
                action_params = {}
            elif not isinstance(action_params, dict):
                action_params = {"value": action_params}
            
            # Handle different action types
            if action_type == "app":
                return self.launch_application(action_params)
            
            elif action_type == "web":
                return self.open_website(action_params)
            
            elif action_type == "volume":
                return self.control_volume(action_params)
            
            elif action_type == "media":
                return self.control_media(action_params)
            
            elif action_type == "shortcut":
                # Get the shortcut parameter from action_params
                shortcut = action_params.get("shortcut", "")
                if not shortcut:
                    logger.error("No shortcut specified in parameters")
                    return False
                return self.send_shortcut(shortcut)
            
            elif action_type == "audio_device":
                # Get the device name parameter from action_params
                device_name = action_params.get("device_name", "")
                logger.debug(f"Audio device switching requested for device: '{device_name}'")
                result = self.switch_audio_device(device_name)
                logger.debug(f"Audio device switching result: {result}")
                return result
            
            elif action_type == "text":
                return self.type_text(action_params)
            
            elif action_type == "command":
                return self.run_command(action_params)
            
            elif action_type == "window":
                return self.control_window(action_params)
            
            elif action_type == "mouse":
                return self.control_mouse(action_params)
            
            elif action_type == "screen":
                return self.capture_screen(action_params)
            
            elif action_type == "setting":
                return self.toggle_setting(action_params)
            
            elif action_type == "powershell":
                return self.run_powershell_command(action_params)
            
            else:
                logger.error(f"Unknown action type: {action_type}")
                return False
                
        except Exception as e:
            logger.error(f"Error executing action: {e}")
            return False
    
    def launch_application(self, action_params):
        """Launch an application
        
        Args:
            action_params (dict): Dictionary containing 'path' key
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            app_path = action_params.get("path", "")
            if not app_path:
                logger.error("No application path provided for app action")
                return False
                
            logger.info(f"Launching application: {app_path}")
            
            if os.name == 'nt':  # Windows
                # Use subprocess with shell=True to handle paths with spaces
                subprocess.Popen(f'start "" "{app_path}"', shell=True)
            elif os.name == 'posix':  # macOS or Linux
                if sys.platform == 'darwin':  # macOS
                    subprocess.Popen(['open', app_path])
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
        """Type text automatically
        
        Args:
            params (dict): Contains the text to type
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if not PYAUTOGUI_AVAILABLE:
                logger.error("pyautogui is not available, text cannot be typed")
                return False
            
            text = params.get("text", "")
            if not text:
                logger.error("No text specified for typing")
                return False
            
            logger.info(f"Typing text: {text[:20]}...")
            pyautogui.write(text)
            return True
        except Exception as e:
            logger.error(f"Failed to type text: {e}")
            return False
    
    def run_command(self, params):
        """Run a system command
        
        Args:
            params (dict): Contains the command to run
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            command = params.get("command", "")
            if not command:
                logger.error("No command specified")
                return False
            
            logger.info(f"Running command: {command}")
            
            # Run the command using subprocess
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Don't wait for process to complete - run it in background
            logger.info(f"Command started: {command}")
            return True
        except Exception as e:
            logger.error(f"Failed to run command: {e}")
            return False
    
    def control_window(self, params):
        """Control window (maximize, minimize, close)
        
        Args:
            params (dict): Contains window action and optionally a window title
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if not PYAUTOGUI_AVAILABLE:
                logger.error("pyautogui is not available, window control not possible")
                return False
            
            action = params.get("action", "")
            if not action:
                logger.error("No window action specified")
                return False
            
            if action == "maximize":
                # Alt+Space, x
                pyautogui.hotkey("alt", "space")
                pyautogui.press("x")
            elif action == "minimize":
                # Alt+Space, n
                pyautogui.hotkey("alt", "space")
                pyautogui.press("n")
            elif action == "close":
                # Alt+F4
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
        """Control mouse (move, click)
        
        Args:
            params (dict): Contains mouse action and coordinates
            
        Returns:
            bool: True if successful, False otherwise
        """
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
    
    def capture_screen(self, params):
        """Capture screenshot
        
        Args:
            params (dict): Contains screenshot options (region, filename)
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if not PYAUTOGUI_AVAILABLE:
                logger.error("pyautogui is not available, screen capture not possible")
                return False
            
            filename = params.get("filename", f"screenshot_{int(time.time())}.png")
            region = params.get("region")
            
            if region:
                # Region is specified as [x, y, width, height]
                screenshot = pyautogui.screenshot(region=region)
            else:
                # Capture full screen
                screenshot = pyautogui.screenshot()
            
            # Save the screenshot
            screenshot.save(filename)
            logger.info(f"Screenshot saved to: {filename}")
            return True
        except Exception as e:
            logger.error(f"Failed to capture screen: {e}")
            return False
    
    def toggle_setting(self, params):
        """Toggle system settings (night mode, airplane mode, etc.)
        
        Args:
            params (dict): Contains the setting to toggle
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            setting = params.get("setting", "")
            if not setting:
                logger.error("No setting specified")
                return False
            
            if self.system == "Windows":
                if setting == "night_mode":
                    # Windows 10 night mode toggle
                    pyautogui.hotkey("win", "a")  # Open action center
                    time.sleep(0.5)
                    # Find and click the night light button
                    # This is a simplified approach and may not work reliably
                    pyautogui.hotkey("win", "a")  # Close action center
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
                
            # Construct PowerShell command
            ps_command = f'powershell.exe -NoProfile -NonInteractive -Command "{command}"'
            
            # Execute the command
            process = subprocess.Popen(
                ps_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True
            )
            
            # Get output and errors
            output, error = process.communicate()
            
            if process.returncode != 0:
                logger.error(f"PowerShell command failed: {error.decode()}")
                return False
                
            logger.debug(f"PowerShell output: {output.decode()}")
            return True
            
        except Exception as e:
            logger.error(f"Error executing PowerShell command: {e}")
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
            interface = devices.Activate(
                IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
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
            elif control == "previous_track":
                pyautogui.press("prevtrack")
            logger.info("Media control sent using pycaw/pyautogui")
        else:
            # Fallback to SendKeys if pycaw is not available
            if control == "play_pause":
                powershell_command = "$WshShell = New-Object -ComObject WScript.Shell; $WshShell.SendKeys([char]179)" #'{PlayPause}'"
                #powershell_command = "$WshShell = New-Object -ComObject WScript.Shell; $WshShell.SendKeys('{MEDIA_PLAY_PAUSE}')"
            elif control == "next_track":
                 powershell_command = "$WshShell = New-Object -ComObject WScript.Shell; $WshShell.SendKeys([char]176)" #'{NextTrack}'"
                #powershell_command = "$WshShell = New-Object -ComObject WScript.Shell; $WshShell.SendKeys('{MEDIA_NEXT_TRACK}')"
            elif control == "previous_track":
                powershell_command = "$WshShell = New-Object -ComObject WScript.Shell; $WshShell.SendKeys([char]177)" #'{PrevTrack}'"
                #powershell_command = "$WshShell = New-Object -ComObject WScript.Shell; $WshShell.SendKeys('{MEDIA_PREV_TRACK}')"
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