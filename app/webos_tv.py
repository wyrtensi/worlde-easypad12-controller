import os
import json
import logging
import asyncio
import aiofiles
from aiowebostv import WebOsClient
from app.utils import ensure_app_directories

logger = logging.getLogger("midi_keyboard.webos")

class WebOSTVManager:
    """Manager class for LG WebOS TV connections and control"""
    
    def __init__(self):
        """Initialize the WebOS TV Manager"""
        self.config_dir, _ = ensure_app_directories()
        self.webos_config_file = os.path.join(self.config_dir, "webos_config.json")
        self.clients = {}  # Store TV clients by IP
        self.connections = {}  # Track connection status
        self.default_commands = self._get_default_commands()
        
        # Store event loop reference
        self.loop = None
        
        # Load existing configuration
        self.config = self._load_config()
        
    def _get_default_commands(self):
        """Get list of default WebOS TV commands"""
        return {
            "Power": {
                "command": "power_off",
                "description": "Power off TV"
            },
            "Home": {
                "command": "button/HOME",
                "description": "Go to Home screen"
            },
            "Back": {
                "command": "button/BACK",
                "description": "Go back"
            },
            "Up": {
                "command": "button/UP", 
                "description": "Navigate up"
            },
            "Down": {
                "command": "button/DOWN",
                "description": "Navigate down"
            },
            "Left": {
                "command": "button/LEFT",
                "description": "Navigate left"
            },
            "Right": {
                "command": "button/RIGHT",
                "description": "Navigate right"
            },
            "Enter": {
                "command": "button/ENTER",
                "description": "Select/Enter"
            },
            "Play": {
                "command": "media.controls/play",
                "description": "Play media"
            },
            "Pause": {
                "command": "media.controls/pause",
                "description": "Pause media"
            },
            "Stop": {
                "command": "media.controls/stop",
                "description": "Stop media"
            },
            "Rewind": {
                "command": "media.controls/rewind",
                "description": "Rewind media"
            },
            "FastForward": {
                "command": "media.controls/fastForward",
                "description": "Fast forward media"
            },
            "VolumeUp": {
                "command": "volume_up",
                "description": "Increase volume"
            },
            "VolumeDown": {
                "command": "volume_down",
                "description": "Decrease volume"
            },
            "Mute": {
                "command": "volume_mute",
                "description": "Mute/unmute"
            },
            "ChannelUp": {
                "command": "button/CHANNELUP",
                "description": "Next channel"
            },
            "ChannelDown": {
                "command": "button/CHANNELDOWN",
                "description": "Previous channel"
            },
            "Netflix": {
                "command": "launcher/netflix",
                "description": "Launch Netflix"
            },
            "YouTube": {
                "command": "launcher/youtube.leanback.v4",
                "description": "Launch YouTube"
            },
            "Amazon": {
                "command": "launcher/amazon",
                "description": "Launch Amazon Prime Video"
            }
        }
        
    def _load_config(self):
        """Load WebOS TV configuration from file"""
        try:
            if os.path.exists(self.webos_config_file):
                with open(self.webos_config_file, 'r') as f:
                    config = json.load(f)
                    logger.info(f"Loaded WebOS TV configuration for {len(config)} TVs")
                    return config
        except Exception as e:
            logger.error(f"Error loading WebOS TV configuration: {e}")
        
        return {}  # Return empty config if file doesn't exist or there was an error
        
    async def _save_config(self):
        """Save WebOS TV configuration to file"""
        try:
            # Make sure config directory exists
            os.makedirs(os.path.dirname(self.webos_config_file), exist_ok=True)
            
            # Prepare and save the config directly
            config_json = json.dumps(self.config, indent=2)
            
            # Use aiofiles for non-blocking file operations
            async with aiofiles.open(self.webos_config_file, 'w') as f:
                await f.write(config_json)
            
            logger.info(f"Saved WebOS TV configuration for {len(self.config)} TVs")
            return True
        except Exception as e:
            logger.error(f"Error saving WebOS TV configuration: {e}")
            return False
    
    def save_config_sync(self):
        """Synchronous wrapper for saving config (for use in non-async contexts)"""
        try:
            if self.loop and self.loop.is_running():
                logger.debug("Using running event loop to save config synchronously")
                future = asyncio.run_coroutine_threadsafe(self._save_config(), self.loop)
                try:
                    # Wait with timeout to avoid blocking indefinitely
                    result = future.result(timeout=2.0)
                    logger.debug(f"Sync config save completed with result: {result}")
                    return result
                except asyncio.TimeoutError:
                    logger.error("Timeout waiting for sync config save")
                    return False
                except Exception as e:
                    logger.error(f"Error in sync save config: {e}")
                    return False
            else:
                logger.debug("Creating new event loop for sync config save")
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    result = loop.run_until_complete(self._save_config())
                    loop.close()
                    logger.debug(f"Sync config save with new loop completed with result: {result}")
                    return result
                except Exception as e:
                    logger.error(f"Error in sync save config with new loop: {e}")
                    if 'loop' in locals():
                        try:
                            loop.close()
                        except:
                            pass
                    return False
        except Exception as e:
            logger.error(f"Unexpected error in save_config_sync: {e}")
            return False
    
    async def get_client(self, ip, client_key=None):
        """Get or create a WebOS TV client for the given IP"""
        # Return existing client if it's already connected
        if ip in self.clients and self.clients[ip]:
            try:
                if self.clients[ip].is_connected():
                    logger.debug(f"Using existing connected client for {ip}")
                    return self.clients[ip]
            except Exception:
                # If there's an error checking connection, create a new client
                pass

        # Create new client
        logger.debug(f"Creating new WebOsClient for {ip}")
        client = WebOsClient(ip)
        if client_key:
            client.client_key = client_key

        self.clients[ip] = client

        # Store this as the active event loop for later use
        self.loop = asyncio.get_event_loop()

        return client
    
    async def is_websocket_valid(self, client):
        """Check if the WebSocket connection is valid with basic checks only"""
        # Simply check if client exists and has basic connection properties
        try:
            # Basic checks only
            if client is None:
                return False
            
            # Check if client reports itself as connected
            if hasattr(client, 'is_connected') and callable(client.is_connected):
                try:
                    connected = client.is_connected()
                    if connected:
                        return True
                except Exception:
                    # If is_connected() throws an exception, continue with other checks
                    pass
                
            # Check websocket attribute and state
            if hasattr(client, 'ws') and client.ws is not None and not client.ws.closed:
                return True
            
            return False
        except Exception as e:
            logger.warning(f"Error in is_websocket_valid: {e}")
            return False

    async def connect(self, ip, client_key=None):
        """Connect to WebOS TV at the specified IP address"""
        logger.info(f"Connecting to WebOS TV at {ip}")
        self.connections[ip] = "connecting"

        try:
            # Create new client
            client = WebOsClient(ip)
            if client_key:
                client.client_key = client_key

            # Store reference to current event loop
            self.loop = asyncio.get_event_loop()
            
            # Connect to the TV
            await client.connect()

            # When connection is successful, store the client key for future connections
            if client.client_key:
                logger.info(f"Successfully connected to TV at {ip}")
                self.config[ip] = {
                    "client_key": client.client_key
                }
                
                # Try to get TV name
                try:
                    info = await client.get_system_info()
                    if info and "model_name" in info:
                        self.config[ip]["name"] = info.get("model_name")
                except Exception as e:
                    logger.warning(f"Couldn't get TV name: {e}")
                    
                # Save config
                await self._save_config()

            # Store the client
            self.clients[ip] = client
            self.connections[ip] = "connected"
            return True, client.client_key

        except Exception as e:
            logger.error(f"Failed to connect to WebOS TV at {ip}: {e}")
            self.connections[ip] = "error"
            return False, None
    
    async def _get_tv_name(self, client):
        """Get the TV's friendly name if available"""
        try:
            info = await client.get_system_info()
            if info and 'modelName' in info:
                return info['modelName']
        except Exception:
            pass
        return None
            
    async def disconnect(self, ip):
        """Disconnect from a WebOS TV"""
        if ip in self.clients and self.clients[ip]:
            try:
                await self.clients[ip].disconnect()
                self.connections[ip] = "disconnected"
                logger.info(f"Disconnected from WebOS TV at {ip}")
                return True
            except Exception as e:
                logger.error(f"Error disconnecting from WebOS TV at {ip}: {e}")
                
        return False
    
    def get_connection_status(self, ip):
        """Get connection status for a specific TV"""
        if ip in self.clients and self.clients[ip]:
            if self.clients[ip].is_connected():
                return "connected"

        return self.connections.get(ip, "disconnected")
            
    async def send_button(self, ip, button):
        """Send a button press command to WebOS TV"""
        return await self.execute_command(ip, button)
            
    async def volume_up(self, ip):
        """Increase volume on WebOS TV"""
        return await self.execute_command(ip, "volume_up")
            
    async def volume_down(self, ip):
        """Decrease volume on WebOS TV"""
        return await self.execute_command(ip, "volume_down")
            
    async def volume_mute(self, ip):
        """Mute/unmute WebOS TV"""
        return await self.execute_command(ip, "volume_mute")
            
    async def power_off(self, ip):
        """Turn off WebOS TV"""
        return await self.execute_command(ip, "power_off")
            
    async def launch_app(self, ip, app_id):
        """Launch an app on WebOS TV"""
        try:
            client = await self.get_client(ip)
            
            # Check if client is connected and has a valid websocket
            if not client.is_connected() or not hasattr(client, 'ws') or client.ws is None:
                logger.info(f"Need to reconnect to WebOS TV at {ip}")
                client_key = self.config.get(ip, {}).get("client_key")
                
                # Reset client if websocket is None
                if not hasattr(client, 'ws') or client.ws is None:
                    logger.info(f"Recreating client for WebOS TV at {ip}")
                    self.clients[ip] = None
                    client = await self.get_client(ip, client_key)
                
                try:
                    # Connect with timeout to avoid hanging
                    await asyncio.wait_for(client.connect(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.error(f"Connection to WebOS TV at {ip} timed out")
                    return False
                except Exception as e:
                    logger.error(f"Failed to connect to WebOS TV at {ip}: {e}")
                    return False
                    
            # Make sure we're connected before sending command
            if not client.is_connected() or not hasattr(client, 'ws') or client.ws is None:
                logger.error(f"WebOS TV at {ip} is not connected, can't launch app")
                return False
                    
            await client.launch_app(app_id)
            logger.info(f"Launched app {app_id} on WebOS TV at {ip}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to launch app {app_id} on WebOS TV at {ip}: {e}")
            return False
            
    async def execute_command(self, ip, command, value=None):
        """Execute a command on the WebOS TV using existing connection when possible"""
        if not ip or not command:
            logger.error("Missing IP or command for WebOS TV control")
            return False
        
        try:
            # Create a fresh client for each command - more reliable than trying to reuse
            client_key = self.config.get(ip, {}).get("client_key")
            logger.debug(f"Creating new connection for command '{command}' to WebOS TV at {ip}")
            
            try:
                # Store reference to current event loop
                self.loop = asyncio.get_event_loop()
                
                # Create a new client each time
                client = WebOsClient(ip)
                if client_key:
                    client.client_key = client_key
                
                # Connect with timeout
                logger.debug(f"Connecting to WebOS TV at {ip}")
                await asyncio.wait_for(client.connect(), timeout=5.0)
                
                # Brief wait after connection
                await asyncio.sleep(0.2)
                
                # Store the client for later use
                self.clients[ip] = client
                
            except asyncio.CancelledError:
                logger.error(f"Connection to WebOS TV at {ip} was cancelled")
                return False
            except asyncio.TimeoutError:
                logger.error(f"Connection to WebOS TV at {ip} timed out")
                return False
            except Exception as e:
                logger.error(f"Error connecting to WebOS TV at {ip}: {e}")
                return False
            
            # Execute the command based on type
            logger.info(f"Executing command '{command}' on WebOS TV at {ip}")
            
            try:
                if command == "power_off":
                    await client.power_off()
                    
                elif command == "volume_up":
                    await client.volume_up()
                    
                elif command == "volume_down":
                    await client.volume_down()
                    
                elif command == "volume_mute":
                    await client.mute()
                    
                elif command == "mute":
                    mute_state = True
                    if value is not None:
                        mute_state = bool(value)
                    await client.mute(mute_state)
                    
                elif command == "channel_up":
                    await client.channel_up()
                    
                elif command == "channel_down":
                    await client.channel_down()
                    
                elif command == "play":
                    await client.play()
                    
                elif command == "pause":
                    await client.pause()
                    
                elif command == "stop":
                    await client.stop()
                    
                elif command == "rewind":
                    await client.rewind()
                    
                elif command == "fast_forward":
                    await client.fast_forward()
                    
                elif command == "set_volume":
                    if value is not None:
                        # Make sure value is within valid range
                        vol_value = max(0, min(100, int(value)))
                        await client.set_volume(vol_value)
                    
                elif command == "launch_app":
                    if value:
                        await client.launch_app(value)
                        
                elif command.startswith("button/"):
                    button = command[7:]
                    await client.button(button)
                    
                elif command.startswith("media.controls/"):
                    # Handle media control commands directly as buttons
                    await client.button(command)
                    
                else:
                    # Try as a direct button command
                    await client.button(command)
                    
                logger.info(f"Successfully executed command '{command}' on WebOS TV at {ip}")
                
                # Don't need to keep the connection open
                try:
                    # Disconnect is non-critical
                    await asyncio.wait_for(client.disconnect(), timeout=1.0)
                except Exception as e:
                    logger.warning(f"Error disconnecting from TV at {ip}: {e}")
                    
                return True
                
            except Exception as e:
                logger.error(f"Failed to execute command '{command}': {e}")
                
                # Try to clean up if we have a connection error
                try:
                    self.clients[ip] = None
                except Exception:
                    pass
                    
                return False
            
        except Exception as e:
            logger.error(f"Error in execute_command: {e}")
            return False
    
    def get_known_tvs(self):
        """Get a dictionary of known TV IPs and their names"""
        return {ip: config.get("name", f"LG TV ({ip})") 
                for ip, config in self.config.items()}
                
    def get_command_list(self):
        """Get list of supported commands"""
        return self.default_commands

    async def channel_up(self, ip):
        """Channel up on WebOS TV"""
        return await self.execute_command(ip, "channel_up")
        
    async def channel_down(self, ip):
        """Channel down on WebOS TV"""
        return await self.execute_command(ip, "channel_down")
        
    async def close_app(self, ip):
        """Close the current app on WebOS TV"""
        return await self.execute_command(ip, "close_app")

    async def cleanup(self):
        """Clean up all WebSocket connections and clients"""
        logger.info("Cleaning up WebOS TV connections")
        for ip, client in list(self.clients.items()):
            try:
                if client and hasattr(client, 'disconnect'):
                    logger.debug(f"Disconnecting WebOS TV at {ip}")
                    try:
                        await asyncio.wait_for(client.disconnect(), timeout=2.0)
                    except (asyncio.TimeoutError, Exception) as e:
                        logger.warning(f"Error during disconnect of {ip}: {e}")
                self.clients[ip] = None
            except Exception as e:
                logger.error(f"Error cleaning up client for {ip}: {e}")
        
        # Clear all clients
        self.clients = {}
        
    def __del__(self):
        """Destructor to ensure proper cleanup"""
        # Try to run cleanup in a new event loop if needed
        try:
            if self.loop and not self.loop.is_closed():
                # If we have an existing loop that's open, use it
                asyncio.run_coroutine_threadsafe(self.cleanup(), self.loop)
            else:
                # Otherwise create a new loop for cleanup
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self.cleanup())
                loop.close()
        except Exception as e:
            logger.error(f"Error during WebOSTVManager cleanup: {e}")
            
    async def force_reconnect(self, ip):
        """Force a reconnection to the WebOS TV"""
        logger.debug(f"Forcing reconnection to WebOS TV at {ip}")
        
        # Clean up any existing client
        if ip in self.clients and self.clients[ip]:
            try:
                client = self.clients[ip]
                # Try to disconnect gracefully
                if hasattr(client, 'disconnect') and callable(client.disconnect):
                    try:
                        await asyncio.wait_for(client.disconnect(), timeout=1.0)
                    except Exception as e:
                        logger.debug(f"Error disconnecting from {ip} during force_reconnect: {e}")
            except Exception as e:
                logger.warning(f"Error cleaning up client for {ip}: {e}")
        
        # Mark as disconnected
        self.clients[ip] = None
        self.connections[ip] = "disconnected"
        
        # Get client key for reconnection
        client_key = self.config.get(ip, {}).get("client_key")
        
        # Attempt reconnection
        success, new_key = await self.connect(ip, client_key)
        
        return success

# Create a singleton instance
webos_manager = WebOSTVManager() 