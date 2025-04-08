import os
import time
import threading
import logging
import json
import subprocess
from pathlib import Path
import tempfile
import traceback
import sys

# Setup logger
logger = logging.getLogger("midi_keyboard.tts")

# Global flag to track availability - initialized here
YANDEX_TTS_AVAILABLE = False
TTS_class = None

# Try to import TTS in a safer way
try:
    from yandex_tts_free import YandexFreeTTS
    TTS_class = YandexFreeTTS
    YANDEX_TTS_AVAILABLE = True
    logger.info("Successfully imported yandex-tts-free package")
except ImportError as e:
    logger.error(f"Failed to import yandex-tts-free: {e}")
    logger.error(f"Import paths: {sys.path}")
    
    # Try alternative import approach
    try:
        logger.info("Attempting alternative import method")
        import importlib
        tts_module = importlib.import_module("yandex_tts_free")
        TTS_class = tts_module.YandexFreeTTS
        YANDEX_TTS_AVAILABLE = True
        logger.info("Alternative import successful")
    except Exception as alt_err:
        logger.error(f"Alternative import failed: {alt_err}")
except Exception as e:
    logger.error(f"Unexpected error importing yandex-tts-free: {e}")
    logger.error(traceback.format_exc())

def try_dynamic_import():
    """Try to dynamically import yandex-tts-free, modifying sys.path if needed"""
    global YANDEX_TTS_AVAILABLE, TTS_class
    
    try:
        logger.info("Attempting dynamic import of yandex-tts-free")
        # Add possible paths
        sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
        sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'site-packages')))
        
        # Try to find the package location
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", "yandex-tts-free"], 
            capture_output=True, 
            text=True
        )
        
        if result.returncode == 0:
            location = None
            for line in result.stdout.splitlines():
                if line.startswith("Location:"):
                    location = line.split(":", 1)[1].strip()
                    break
            
            if location:
                logger.info(f"Found yandex-tts-free at: {location}")
                sys.path.append(location)
                
                # Try importing again
                from yandex_tts_free import YandexFreeTTS
                TTS_class = YandexFreeTTS
                YANDEX_TTS_AVAILABLE = True
                logger.info("Successfully imported yandex-tts-free after path adjustment")
                return True
    except Exception as e:
        logger.error(f"Dynamic import attempt failed: {e}")
        logger.error(traceback.format_exc())
    
    return False

class TextToSpeechManager:
    def __init__(self):
        """Initialize the Text-to-Speech manager"""
        self.active_process = None
        self.process_lock = threading.Lock()
        self.temp_dir = tempfile.gettempdir()
        # Use a temp file path that includes a timestamp to make it unique for each generation
        self.temp_file_base = os.path.join(self.temp_dir, "midi_app_tts")
        self.temp_file_path = f"{self.temp_file_base}_{int(time.time())}.mp3"
        self.stopped = threading.Event()
        # Keep track of pygame initialization state
        self.pygame_initialized = False
        
        # Available languages and voices
        self.languages = {
            "ru_RU": {
                "name": "Russian",
                "voices": {
                    "alena": "Alena",
                    "filipp": "Filipp",
                    "jane": "Jane",
                    "omazh": "Omazh",
                    "zahar": "Zahar",
                    "ermil": "Ermil"
                }
            }
        }
        
        # Available voice moods (emotions)
        self.voice_moods = {
            "neutral": "Neutral",
            "good": "Good",
            "evil": "Evil",
            "mixed": "Mixed"
        }
        
        # Audio frequencies in Hz
        self.audio_frequencies = {
            "8000": "8 kHz",
            "16000": "16 kHz",
            "24000": "24 kHz",
            "44100": "44.1 kHz",
            "48000": "48 kHz"
        }
        
        logger.info("Text-to-Speech Manager initialized")
        if not YANDEX_TTS_AVAILABLE:
            logger.warning("yandex-tts-free package not available. Install with 'pip install yandex-tts-free'")
            logger.info("Checking pip installation...")
            try:
                import subprocess
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "list"], 
                    capture_output=True, 
                    text=True
                )
                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        if "yandex" in line.lower():
                            logger.info(f"Found package: {line.strip()}")
            except Exception as e:
                logger.error(f"Error checking pip packages: {e}")
    
    def check_prerequisites(self):
        """Check if all required components are available"""
        global YANDEX_TTS_AVAILABLE
        
        if not YANDEX_TTS_AVAILABLE:
            logger.error("Yandex TTS package not available")
            return try_dynamic_import()
        return True
        
    def get_clipboard_text(self):
        """Get text from clipboard with multiple fallback mechanisms"""
        # Try to import pyperclip here to avoid global import issues
        clipboard_text = ""
        
        try:
            logger.debug("Attempting to get clipboard text via pyperclip")
            import pyperclip
            text = pyperclip.paste()
            if text:
                logger.debug(f"Successfully got text from clipboard ({len(text)} chars)")
                return text
            else:
                logger.warning("Clipboard appears to be empty")
        except Exception as e:
            logger.error(f"Error getting clipboard text via pyperclip: {e}")
        
        # Fallback to Windows clipboard if pyperclip fails
        if os.name == 'nt':
            try:
                logger.debug("Attempting to get clipboard text via Windows API (ctypes)")
                import ctypes
                
                # Windows clipboard access via ctypes
                CF_UNICODETEXT = 13
                
                user32 = ctypes.windll.user32
                kernel32 = ctypes.windll.kernel32
                
                if not user32.OpenClipboard(0):
                    logger.error("Failed to open clipboard")
                    return ""
                
                try:
                    if user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                        data = user32.GetClipboardData(CF_UNICODETEXT)
                        if data:
                            text_ptr = kernel32.GlobalLock(data)
                            if text_ptr:
                                try:
                                    text = ctypes.wstring_at(text_ptr)
                                    logger.debug(f"Got text from Windows clipboard API ({len(text)} chars)")
                                    return text
                                finally:
                                    kernel32.GlobalUnlock(data)
                    else:
                        logger.warning("No text available in clipboard")
                finally:
                    user32.CloseClipboard()
            except Exception as e:
                logger.error(f"Error accessing Windows clipboard: {e}")
        
        # Another fallback approach for Windows
        if os.name == 'nt':
            try:
                logger.debug("Attempting to get clipboard text via PowerShell")
                import subprocess
                result = subprocess.run(
                    ["powershell", "-command", "Get-Clipboard"], 
                    capture_output=True, 
                    text=True
                )
                
                if result.returncode == 0 and result.stdout:
                    text = result.stdout.strip()
                    logger.debug(f"Got text from PowerShell clipboard ({len(text)} chars)")
                    return text
                else:
                    logger.warning(f"PowerShell clipboard access failed: {result.stderr}")
            except Exception as e:
                logger.error(f"Error with PowerShell clipboard access: {e}")
        
        # If everything failed, return empty string
        logger.error("All clipboard access methods failed")
        return ""
    
    def stop_current_playback(self):
        """Stop any currently playing TTS"""
        with self.process_lock:
            if self.active_process is not None:
                try:
                    self.stopped.set()
                    self.active_process.terminate()
                    logger.info("Terminated previous TTS playback")
                except Exception as e:
                    logger.error(f"Error stopping playback: {e}")
                finally:
                    self.active_process = None
                    # Reset the stopped event
                    self.stopped.clear()
            
            # Stop pygame playback if it's active
            try:
                if self.pygame_initialized:
                    import pygame
                    if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                        pygame.mixer.music.stop()
                        pygame.mixer.quit()
                        logger.info("Stopped pygame audio playback")
            except Exception as e:
                logger.error(f"Error stopping pygame playback: {e}")
    
    def get_selected_text(self):
        """Get currently selected text using various methods"""
        # Windows-specific selection capture
        if os.name == 'nt':
            try:
                # Simulate Ctrl+C to copy selected text to clipboard
                import ctypes
                from ctypes import wintypes
                
                # Windows API constants
                VK_CONTROL = 0x11
                VK_C = 0x43
                KEYEVENTF_KEYUP = 0x0002
                INPUT_KEYBOARD = 1
                
                # Send Ctrl key down
                ctypes.windll.user32.keybd_event(VK_CONTROL, 0, 0, 0)
                # Send C key down
                ctypes.windll.user32.keybd_event(VK_C, 0, 0, 0)
                # Small delay
                time.sleep(0.05)
                # Send C key up
                ctypes.windll.user32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
                # Send Ctrl key up
                ctypes.windll.user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
                
                # Give time for clipboard to update
                time.sleep(0.1)
                
                logger.info("Simulated Ctrl+C to copy selected text")
                return True
            except Exception as e:
                logger.error(f"Error simulating Ctrl+C: {e}")
                return False
        else:
            # For other platforms, we would need platform-specific code
            logger.warning("Text selection not implemented for this platform")
            return False
    
    def play_text(self, config):
        """
        Play text-to-speech with the given configuration
        
        config: {
            "language": "ru_RU", "en_US", or "auto"
            "voice": Voice name (string)
            "mood": Voice mood (string)
            "frequency": Audio frequency in Hz (string)
            "text_source": "selection" or "clipboard"
        }
        """
        logger.info(f"Attempting to play text with config: {config}")
        
        # Check if TTS is available, try to import if not
        if not YANDEX_TTS_AVAILABLE:
            logger.error("TTS not available, attempting to import")
            if not self.check_prerequisites():
                logger.error("Failed to import TTS library")
                return False
            
            # Double-check after trying to import
            if not YANDEX_TTS_AVAILABLE:
                logger.error("TTS still not available after import attempt")
                return False
        
        # Stop any current playback
        self.stop_current_playback()
        
        # Generate a new unique temp file path for this request
        self.temp_file_path = f"{self.temp_file_base}_{int(time.time())}.mp3"
        
        # If text source is 'selection', try to get the selected text first
        if config.get("text_source") == "selection":
            logger.info("Attempting to get selected text")
            self.get_selected_text()  # This will copy selection to clipboard
        
        # Get the text from clipboard
        text = None
        try:
            if config.get("text_source", "clipboard") == "clipboard" or config.get("text_source") == "selection":
                text = self.get_clipboard_text()
                if text:
                    logger.info(f"Got text from clipboard ({len(text)} characters)")
                else:
                    logger.warning("Clipboard text is empty")
            else:
                # For future implementation (direct text input)
                text = config.get("text", "")
                if text:
                    logger.info(f"Using provided text ({len(text)} characters)")
                else:
                    logger.warning("Provided text is empty")
        except Exception as e:
            logger.error(f"Error getting text: {e}")
            logger.error(traceback.format_exc())
            return False
            
        if not text:
            logger.warning("No text available for TTS")
            return False
            
        # Launch in a separate thread to not block the main thread
        try:
            tts_thread = threading.Thread(
                target=self._process_tts,
                args=(text, config),
                daemon=True
            )
            tts_thread.start()
            logger.info("Started TTS processing thread")
            return True
        except Exception as e:
            logger.error(f"Failed to start TTS thread: {e}")
            logger.error(traceback.format_exc())
            return False
    
    def _process_tts(self, text, config):
        """Process TTS in a separate thread"""
        try:
            # Extract configuration values with defaults
            language = config.get("language", "auto")
            voice = config.get("voice", "auto")
            mood = config.get("mood", "neutral")
            
            try:
                frequency = int(config.get("frequency", "24000"))
            except (TypeError, ValueError):
                frequency = 24000
                logger.warning(f"Invalid frequency value, using default: {frequency}")
            
            logger.info(f"Starting TTS: language={language}, voice={voice}, mood={mood}, frequency={frequency}")
            logger.debug(f"Text length: {len(text)} characters")
            
            # Initialize TTS with extensive error handling
            tts = None
            try:
                logger.debug("Initializing TTS object")
                if TTS_class is None:
                    logger.error("TTS class is not available")
                    return False
                
                # Create TTS instance without parameters
                tts = TTS_class()
                logger.debug("TTS object initialized successfully")
            except NameError as e:
                logger.error(f"TTS class not found: {e}. This indicates an import problem.")
                return False
            except TypeError as e:
                logger.error(f"TTS initialization type error: {e}. Check parameter types.")
                return False
            except Exception as e:
                logger.error(f"Failed to initialize TTS object: {e}")
                logger.error(traceback.format_exc())
                return False
            
            # Generate speech
            try:
                # Make sure temp directory exists
                os.makedirs(os.path.dirname(self.temp_file_path), exist_ok=True)
                
                # Remove any existing temp file
                if os.path.exists(self.temp_file_path):
                    try:
                        os.remove(self.temp_file_path)
                        logger.debug(f"Removed existing temp file: {self.temp_file_path}")
                    except Exception as e:
                        logger.warning(f"Could not remove temp file: {e}")
                else:
                    logger.debug(f"No existing temp file to remove at: {self.temp_file_path}")
                
                # Generate and save TTS audio
                logger.debug("Generating speech...")
                
                # Get the directory and filename for the output
                output_dir = os.path.dirname(self.temp_file_path)
                filename = os.path.basename(self.temp_file_path)
                
                try:
                    # For long texts, split into smaller chunks to avoid API limits
                    # and merging issues
                    MAX_CHARS_PER_REQUEST = 800  # Reduced chunk size for API limits
                    if len(text) > MAX_CHARS_PER_REQUEST:
                        logger.info(f"Text is long ({len(text)} chars), processing in chunks")
                        
                        # Create a unique session ID for this TTS generation
                        session_id = int(time.time() * 1000)
                        
                        # Split text into sentences to avoid cutting words
                        import re
                        # Split on sentence endings and line breaks
                        sentences = [s.strip() for s in re.split(r'([.!?\n]+)', text) if s.strip()]
                        
                        # Initialize pygame for streaming playback
                        try:
                            import pygame
                            pygame.mixer.init()
                            self.pygame_initialized = True
                            logger.info("Initialized pygame mixer for streaming playback")
                        except Exception as pygame_init_err:
                            logger.error(f"Failed to initialize pygame mixer: {pygame_init_err}")
                            pygame = None
                            
                        # Create a queue for producer-consumer pattern
                        import queue
                        audio_queue = queue.Queue()
                        generation_complete = threading.Event()
                        
                        # Producer function to generate chunks
                        def generate_chunks():
                            try:
                                # Process each sentence separately and collect audio files
                                current_chunk = ""
                                chunk_count = 1
                                
                                for sentence in sentences:
                                    # If adding this sentence would exceed the limit, process the current chunk
                                    if len(current_chunk) + len(sentence) > MAX_CHARS_PER_REQUEST and current_chunk:
                                        # Generate temporary filename with session ID
                                        temp_file = os.path.join(output_dir, f"chunk_{session_id}_{chunk_count}.mp3")
                                        logger.debug(f"Processing chunk {chunk_count} ({len(current_chunk)} chars)")
                                        
                                        # Generate audio for this chunk
                                        chunk_tts = TTS_class()
                                        try:
                                            # Clean the text before sending to API
                                            clean_text = current_chunk.strip().replace('\r', ' ').replace('\n', ' ')
                                            while '  ' in clean_text:  # Remove double spaces
                                                clean_text = clean_text.replace('  ', ' ')
                                                
                                            chunk_tts.generate_speech_ya(
                                                output_path=output_dir,
                                                filename=os.path.basename(temp_file),
                                                text=clean_text,
                                                speaker=voice,
                                                mood=mood
                                            )
                                            if os.path.exists(temp_file) and os.path.getsize(temp_file) > 0:
                                                # Add to queue for playback
                                                audio_queue.put((chunk_count, temp_file))
                                                logger.debug(f"Successfully generated chunk {chunk_count}")
                                                chunk_count += 1
                                            else:
                                                logger.error(f"Failed to generate audio for chunk {chunk_count}")
                                        except Exception as chunk_err:
                                            logger.error(f"Error processing chunk {chunk_count}: {chunk_err}")
                                        
                                        # Reset current chunk
                                        current_chunk = sentence
                                    else:
                                        # Add sentence to current chunk
                                        if current_chunk:
                                            current_chunk += " " + sentence
                                        else:
                                            current_chunk = sentence
                                
                                # Process the final chunk if it's not empty
                                if current_chunk:
                                    temp_file = os.path.join(output_dir, f"chunk_{session_id}_{chunk_count}.mp3")
                                    logger.debug(f"Processing final chunk {chunk_count} ({len(current_chunk)} chars)")
                                    
                                    chunk_tts = TTS_class()
                                    try:
                                        # Clean the text before sending to API
                                        clean_text = current_chunk.strip().replace('\r', ' ').replace('\n', ' ')
                                        while '  ' in clean_text:  # Remove double spaces
                                            clean_text = clean_text.replace('  ', ' ')
                                            
                                        chunk_tts.generate_speech_ya(
                                            output_path=output_dir,
                                            filename=os.path.basename(temp_file),
                                            text=clean_text,
                                            speaker=voice,
                                            mood=mood
                                        )
                                        if os.path.exists(temp_file) and os.path.getsize(temp_file) > 0:
                                            # Add to queue for playback
                                            audio_queue.put((chunk_count, temp_file))
                                            logger.debug(f"Successfully generated final chunk")
                                        else:
                                            logger.error(f"Failed to generate audio for final chunk")
                                    except Exception as chunk_err:
                                        logger.error(f"Error processing final chunk: {chunk_err}")
                                
                                # Signal that generation is complete
                                generation_complete.set()
                                logger.info("All chunks generated")
                            except Exception as e:
                                logger.error(f"Error in chunk generation: {e}")
                                generation_complete.set()  # Ensure we signal completion even on error
                        
                        # Consumer function to play chunks
                        def play_chunks():
                            try:
                                if not pygame or not pygame.mixer.get_init():
                                    logger.error("Pygame mixer not initialized, cannot play chunks")
                                    return
                                
                                # Track the next chunk number to play
                                next_chunk = 1
                                chunks_played = 0
                                
                                # Keep playing until all chunks are played or stopped
                                while not self.stopped.is_set():
                                    try:
                                        # Check if we have the next chunk in the queue
                                        if not audio_queue.empty():
                                            chunk_num, temp_file = audio_queue.get()
                                            
                                            # If this is the next chunk to play, play it
                                            if chunk_num == next_chunk:
                                                logger.info(f"Playing chunk {chunk_num}")
                                                sound = pygame.mixer.Sound(temp_file)
                                                channel = sound.play()
                                                
                                                # Wait for the sound to finish playing
                                                while channel.get_busy() and not self.stopped.is_set():
                                                    pygame.time.wait(100)
                                                
                                                # Clean up the chunk file after playing
                                                try:
                                                    os.remove(temp_file)
                                                    logger.debug(f"Removed temp file after playback: {temp_file}")
                                                except Exception as e:
                                                    logger.warning(f"Could not remove temp file {temp_file}: {e}")
                                                
                                                chunks_played += 1
                                                next_chunk += 1
                                            else:
                                                # Put it back in the queue if it's not the next one
                                                audio_queue.put((chunk_num, temp_file))
                                        
                                        # If queue is empty and generation is complete, we're done
                                        if audio_queue.empty() and generation_complete.is_set():
                                            logger.info(f"All {chunks_played} chunks played")
                                            break
                                        
                                        # Small sleep to prevent CPU hogging
                                        pygame.time.wait(50)
                                    except Exception as e:
                                        logger.error(f"Error playing chunk: {e}")
                                        break
                            except Exception as e:
                                logger.error(f"Error in chunk playback: {e}")
                            finally:
                                # Clean up pygame
                                if pygame and pygame.mixer.get_init():
                                    pygame.mixer.quit()
                                    self.pygame_initialized = False
                        
                        # Start producer and consumer threads
                        producer_thread = threading.Thread(target=generate_chunks)
                        consumer_thread = threading.Thread(target=play_chunks)
                        
                        producer_thread.daemon = True
                        consumer_thread.daemon = True
                        
                        producer_thread.start()
                        consumer_thread.start()
                        
                        # Wait for both threads to complete
                        producer_thread.join()
                        consumer_thread.join()
                        
                        logger.info("Streaming playback completed")
                    else:
                        # For shorter texts, use standard method
                        try:
                            # Try generate_speech_ya method (direct approach)
                            tts.generate_speech_ya(
                                output_path=output_dir,
                                filename=filename,
                                text=text,
                                speaker=voice,
                                mood=mood
                            )
                            logger.debug("Successfully generated audio with generate_speech_ya method")
                        except Exception as gen_err:
                            logger.error(f"Error with generate_speech_ya method: {gen_err}")
                            return False
                except Exception as e:
                    logger.error(f"Error in TTS generation: {e}")
                    logger.error(traceback.format_exc())
                    return False
                
                if not os.path.exists(self.temp_file_path):
                    logger.error("TTS file generation failed - output file not created")
                    return False
                
                logger.info(f"Speech generated successfully to: {self.temp_file_path}")
                file_size = os.path.getsize(self.temp_file_path)
                logger.debug(f"Generated file size: {file_size} bytes")
                
                # Play the audio
                if os.name == 'nt':  # Windows
                    # Start playback process
                    with self.process_lock:
                        if not self.stopped.is_set():
                            logger.debug("Starting Windows audio playback...")
                            
                            # Use pygame for background audio playback
                            try:
                                # Try to import pygame - if not available, we'll install it
                                try:
                                    import pygame
                                except ImportError:
                                    logger.info("pygame not found, attempting to install...")
                                    subprocess.run(
                                        [sys.executable, "-m", "pip", "install", "pygame"],
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE
                                    )
                                    import pygame
                                
                                # Close any existing pygame mixer
                                if pygame.mixer.get_init():
                                    pygame.mixer.quit()
                                    time.sleep(0.1)  # Give time for resources to be released
                                
                                # Initialize pygame mixer
                                pygame.mixer.init()
                                self.pygame_initialized = True
                                
                                # Wait a moment to ensure the file is fully available
                                time.sleep(0.1)
                                
                                # Load and play the audio
                                pygame.mixer.music.load(self.temp_file_path)
                                pygame.mixer.music.play()
                                
                                logger.info("Audio playback started with pygame (background)")
                                
                                # Don't exit immediately - wait briefly so playback can start
                                time.sleep(0.5)
                                
                                # We won't wait for completion, as that would block the thread
                                # The audio will continue playing in the background
                                
                            except Exception as e:
                                logger.error(f"Failed to play audio with pygame: {e}")
                                logger.error(traceback.format_exc())
                                
                                # Fallback to a Windows Media Foundation approach
                                try:
                                    # Use PowerShell with Windows.Media.Playback namespace
                                    ps_command = """
                                    Add-Type -AssemblyName PresentationCore;
                                    $mediaPlayer = New-Object System.Windows.Media.MediaPlayer;
                                    $mediaPlayer.Open('{0}');
                                    $mediaPlayer.Play();
                                    Start-Sleep -Milliseconds 500;
                                    # Return immediately without waiting for completion
                                    """.format(self.temp_file_path.replace('\\', '\\\\'))
                                    
                                    self.active_process = subprocess.Popen(
                                        ["powershell", "-Command", ps_command],
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE
                                    )
                                    
                                    logger.info("Audio playback started with PowerShell MediaPlayer (fallback)")
                                    
                                except Exception as ps_err:
                                    logger.error(f"Failed to play audio with PowerShell fallback: {ps_err}")
                            
                            self.active_process = None
                else:  # macOS / Linux
                    # For macOS / Linux, use appropriate player
                    with self.process_lock:
                        if not self.stopped.is_set():
                            try:
                                which_afplay = subprocess.call(["which", "afplay"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                                logger.debug(f"Check for afplay returned: {which_afplay}")
                                
                                if which_afplay == 0:
                                    # macOS
                                    logger.debug("Starting macOS audio playback...")
                                    self.active_process = subprocess.Popen(
                                        ["afplay", self.temp_file_path],
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE
                                    )
                                else:
                                    # Linux (with mpg123)
                                    logger.debug("Starting Linux audio playback...")
                                    self.active_process = subprocess.Popen(
                                        ["mpg123", self.temp_file_path],
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE
                                    )
                            except Exception as e:
                                logger.error(f"Error starting playback process: {e}")
                                return False
                                
                            # Wait for process to complete
                            stdout, stderr = self.active_process.communicate()
                            return_code = self.active_process.returncode
                            
                            if return_code != 0 and not self.stopped.is_set():
                                logger.error(f"Audio playback failed with return code {return_code}")
                                logger.error(f"Stderr: {stderr.decode() if stderr else 'None'}")
                            else:
                                logger.info("Audio playback completed successfully")
                            
                            self.active_process = None
                
                logger.info("TTS playback completed")
                return True
                
            except Exception as e:
                logger.error(f"Error in TTS generation or playback: {e}")
                logger.error(traceback.format_exc())
                return False
                
        except Exception as e:
            logger.error(f"Error in TTS processing: {e}")
            logger.error(traceback.format_exc())
            return False

    def get_language_list(self):
        """Get list of available languages"""
        return {code: data["name"] for code, data in self.languages.items()}
    
    def get_voice_list(self, language_code):
        """Get list of available voices for a language"""
        if language_code in self.languages:
            return self.languages[language_code]["voices"]
        return {}
    
    def get_mood_list(self):
        """Get list of available voice moods"""
        return self.voice_moods
    
    def get_frequency_list(self):
        """Get list of available audio frequencies"""
        return self.audio_frequencies


# Singleton instance
tts_manager = TextToSpeechManager() 