import os
import json
import logging
from datetime import datetime
import sys
import platform
from pathlib import Path

# Setup logging
def setup_logging():
    """Set up logging for the application"""
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    
    log_file = os.path.join(log_dir, f"midi_controller_{datetime.now().strftime('%Y%m%d')}.log")
    
    logging.basicConfig(
        level=logging.DEBUG,  # Changed to DEBUG to capture more detail for troubleshooting
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    
    return logging.getLogger("midi_controller")

# Create a global logger for use throughout the module
logger = logging.getLogger('midi_keyboard')
logger.setLevel(logging.DEBUG)

# Create formatter for use throughout the module
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

def get_app_root():
    """Get the application root directory"""
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        return os.path.dirname(sys.executable)
    else:
        # Running in development
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_config_dir():
    """Get the configuration directory path"""
    app_root = get_app_root()
    config_dir = os.path.join(app_root, "config")
    return config_dir

def ensure_app_directories():
    """Ensure all application directories exist"""
    app_root = get_app_root()
    
    # Create config directory
    config_dir = os.path.join(app_root, "config")
    os.makedirs(config_dir, exist_ok=True)
    
    # Create logs directory
    logs_dir = os.path.join(app_root, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    
    # Create assets directory
    assets_dir = os.path.join(app_root, "app", "assets")
    os.makedirs(assets_dir, exist_ok=True)
    
    return config_dir, logs_dir

# Theme functions
def get_dark_theme():
    """Get the dark theme configuration"""
    return {
        "dark_bg": "#1a1a1a",
        "primary_color": "#ff69b4",  # Hot pink
        "secondary_color": "#00b0b0",  # Teal
        "button_active_color": "#ff1493",  # Deeper pink
        "highlight_color": "#00ffff",  # Cyan
        "text_color": "#ffffff",
        "sidebar_bg": "#222222",
        "card_bg": "#2a2a2a",
        "success_color": "#50fa7b",
        "warning_color": "#ffb86c",
        "error_color": "#ff5555"
    }

def get_light_theme():
    """Get the light theme configuration (not actively used)"""
    return {
        "dark_bg": "#f0f0f0",
        "primary_color": "#ff69b4",  # Hot pink
        "secondary_color": "#00b0b0",  # Teal
        "button_active_color": "#ff1493",  # Deeper pink
        "highlight_color": "#00ffff",  # Cyan
        "text_color": "#333333",
        "sidebar_bg": "#e0e0e0",
        "card_bg": "#f5f5f5",
        "success_color": "#4caf50",
        "warning_color": "#ff9800",
        "error_color": "#f44336"
    }

# MIDI helpers
def midi_note_to_name(note):
    """Convert MIDI note number to note name"""
    notes = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    octave = note // 12 - 1
    note_name = notes[note % 12]
    return f"{note_name}{octave}"

def load_midi_mapping():
    """Load MIDI device mapping from config or return default"""
    try:
        config_dir = get_config_dir()
        mapping_file = os.path.join(config_dir, "midi_mapping.json")
        
        if os.path.exists(mapping_file):
            with open(mapping_file, 'r') as f:
                mapping = json.load(f)
                logger.info(f"Loaded MIDI mapping with {len(mapping.get('note_mapping', {}))} note mappings")
                return mapping
    except Exception as e:
        logger.error(f"Error loading MIDI mapping: {e}")
    
    # Default mapping with basic layout for APC key 25
    default_mapping = {
        "device_name": "APC Key 25",
        "note_mapping": {},
        "layout": {
            "rows": [
                [40, 41, 42, 43, 44, 45],
                [46, 47, 48, 49, 50, 51]
            ],
            "slider": ["sliderA"],
            "controls": [1, 2, 3, 4, 5, 6, 7, 8]
        },
        "button_names": {
            "1": "Button 1",
            "2": "Button 2",
            "3": "Button 3",
            "4": "Button 4",
            "5": "Button 5",
            "6": "Button 6",
            "7": "Button 7",
            "8": "Button 8",
            "40": "Pad 1",
            "41": "Pad 2",
            "42": "Pad 3",
            "43": "Pad 4",
            "44": "Pad 5",
            "45": "Pad 6",
            "46": "Pad 7",
            "47": "Pad 8",
            "48": "Pad 9",
            "49": "Pad 10",
            "50": "Pad 11",
            "51": "Pad 12",
            "sliderA": "Volume"
        }
    }
    
    logger.info(f"Using default MIDI mapping for {default_mapping['device_name']}")
    return default_mapping

def get_action_types():
    """Get available action types with descriptions"""
    return {
        "app": {
            "name": "Launch Application",
            "description": "Launch a desktop application when the button is pressed."
      },
        "toggle_app": {
            "name": "Toggle Application",
            "description": "Start the application if it's not running, or kill it if it is running."
        },
        "web": {
            "name": "Open Website",
            "description": "Open a website in your default browser when the button is pressed."
        },
        "volume": {
            "name": "Volume Control",
            "description": "Adjust system volume when the button is pressed or slider is moved."
        },
        "audio_device": {
            "name": "Switch Audio Device",
            "description": "Switch between audio output devices when the button is pressed."
        },
        "shortcut": {
            "name": "Keyboard Shortcut",
            "description": "Send a keyboard shortcut when the button is pressed (e.g., Ctrl+C, Alt+Tab)."
        },
        "media": {
            "name": "Media Control",
            "description": "Control media playback (play/pause, next, previous, etc.)."
        },
        "command": {
            "name": "System Command",
            "description": "Execute a system command or script."
        },
        "powershell": {
            "name": "PowerShell Command",
            "description": "Execute a PowerShell command or script."
        },
        "text": {
            "name": "Type Text",
            "description": "Type text automatically when the button is pressed."
        },
        "speech_to_text": {
            "name": "Speech to Text",
            "description": "Recognize speech and type it as text while holding the button."
        },
        "ask_chatgpt": {
            "name": "Ask ChatGPT",
            "description": "Record speech while holding the button, send to ChatGPT, and paste the response."
        },
        "text_to_speech": {
            "name": "Text to Speech",
            "description": "Read selected text aloud using text-to-speech."
        },
        "wake_on_lan": {
            "name": "Wake On LAN",
            "description": "Send a Wake-on-LAN magic packet to wake up a device on the network."
        },
        "webos_tv": {
            "name": "WebOS TV Control",
            "description": "Control LG TV with WebOS, send remote commands, launch apps, and more."
        }
    }

def get_media_controls():
    """Get available media control actions"""
    return {
        "play_pause": {
            "name": "Play/Pause",
            "description": "Toggle between play and pause for the current media",
            "shortcut": "media_play_pause"
        },
        "next_track": {
            "name": "Next Track",
            "description": "Skip to the next track",
            "shortcut": "media_next_track"
        },
        "prev_track": {
            "name": "Previous Track",
            "description": "Go back to the previous track",
            "shortcut": "media_prev_track"
        },
        "stop": {
            "name": "Stop",
            "description": "Stop playback",
            "shortcut": "media_stop"
        },
        "volume_up": {
            "name": "Volume Up",
            "description": "Increase the system volume",
            "shortcut": "volume_up"
        },
        "volume_down": {
            "name": "Volume Down",
            "description": "Decrease the system volume",
            "shortcut": "volume_down"
        },
        "volume_mute": {
            "name": "Mute/Unmute",
            "description": "Toggle mute for system audio",
            "shortcut": "volume_mute"
        }
    }

def save_button_config(button_id, config):
    """Save configuration for a specific button"""
    config_dir, _ = ensure_app_directories()
    config_file = os.path.join(config_dir, f'button_{button_id}.json')
    
    try:
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)
            logger.info(f"Saved configuration for button {button_id}")
        return True
    except Exception as e:
        logger.error(f"Error saving button configuration: {e}")
        return False

def load_button_config(button_id):
    """Load configuration for a specific button"""
    config_dir, _ = ensure_app_directories()
    config_file = os.path.join(config_dir, f'button_{button_id}.json')
    
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
                # Handle backward compatibility for command and powershell
                if config.get("action_type") in ["command", "powershell"]:
                    action_data = config.get("action_data", {})
                    if "command" in action_data and "commands" not in action_data:
                        # Convert single command to list
                        config["action_data"]["commands"] = [{"command": action_data["command"], "delay_ms": 0}]
                        del action_data["command"]
                logger.info(f"Loaded configuration for button {button_id}")
                return config
        except Exception as e:
            logger.error(f"Error loading button configuration: {e}")
    
    # Default configuration
    return {
        "action_type": None,
        "action_data": {},
        "enabled": True,
        "name": f"Button {button_id}"
    }

def get_saved_button_configs():
    """Get all saved button configurations"""
    config_dir, _ = ensure_app_directories()
    configs = {}
    
    try:
        # List all button configuration files
        logger.debug(f"Checking for button configs in: {config_dir}")
        if os.path.exists(config_dir):
            for filename in os.listdir(config_dir):
                if filename.startswith('button_') and filename.endswith('.json'):
                    button_id = filename[7:-5]  # Extract button_id from filename (button_X.json)
                    logger.debug(f"Found config file for button {button_id}")
                    configs[button_id] = load_button_config(button_id)
        else:
            logger.warning(f"Config directory does not exist: {config_dir}")
        
        logger.info(f"Loaded {len(configs)} button configurations from individual files")
    except Exception as e:
        logger.error(f"Error loading button configurations: {e}")
    
    return configs