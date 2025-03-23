import rtmidi
import time
import threading
import os
import json
import logging

class MIDIController:
    def __init__(self, callback=None):
        self.callback = callback
        self.midi_in = rtmidi.MidiIn()
        self.available_ports = self.midi_in.get_ports()
        self.is_connected = False
        self.port_name = None
        self.monitoring = False
        self.monitor_thread = None
        
        # Initialize logger
        self.logger = logging.getLogger("midi_controller.midi")
        
        # Load direct input mappings
        self.load_mapping()
    
    def load_mapping(self):
        """Load MIDI mappings for direct input"""
        try:
            from app.utils import load_midi_mapping
            self.mapping = load_midi_mapping()
            self.direct_input = self.mapping.get("direct_input", {})
            self.logger.info(f"Loaded MIDI mapping with {len(self.direct_input.get('notes', {}))} note mappings")
        except Exception as e:
            self.logger.error(f"Error loading MIDI mapping: {e}")
            self.direct_input = {"notes": {}, "controls": {}}
    
    def get_available_ports(self):
        """Get a list of available MIDI input ports"""
        self.available_ports = self.midi_in.get_ports()
        return self.available_ports
    
    def connect_to_device(self, port_name=None, port_index=None):
        """Connect to a MIDI device by name or index"""
        try:
            if self.is_connected:
                self.disconnect()
                
            if port_name:
                # Find the index of the port with the given name
                for i, name in enumerate(self.available_ports):
                    if port_name.lower() in name.lower():
                        port_index = i
                        self.port_name = name
                        break
                else:
                    return False, f"Device '{port_name}' not found"
            
            if port_index is not None and 0 <= port_index < len(self.available_ports):
                self.midi_in.open_port(port_index)
                if not self.port_name:
                    self.port_name = self.available_ports[port_index]
                self.is_connected = True
                self.logger.info(f"Connected to MIDI device: {self.port_name}")
                return True, f"Connected to {self.port_name}"
            else:
                return False, "Invalid port index"
                
        except Exception as e:
            return False, f"Error connecting to MIDI device: {str(e)}"
    
    def disconnect(self):
        """Disconnect from the current MIDI device"""
        if self.is_connected:
            self.stop_monitoring()
            self.midi_in.close_port()
            self.is_connected = False
            self.port_name = None
            self.logger.info("Disconnected from MIDI device")
            return True, "Disconnected from MIDI device"
        return False, "No device connected"
    
    def start_monitoring(self):
        """Start monitoring MIDI messages"""
        if not self.is_connected:
            return False, "Not connected to any MIDI device"
        
        if self.monitoring:
            return True, "Already monitoring"
        
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        self.logger.info("Started monitoring MIDI messages")
        return True, "Started monitoring MIDI messages"
    
    def stop_monitoring(self):
        """Stop monitoring MIDI messages"""
        self.monitoring = False
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(1.0)
        self.logger.info("Stopped monitoring MIDI messages")
        return True, "Stopped monitoring MIDI messages"
    
    def _monitor_loop(self):
        """Background thread for monitoring MIDI messages"""
        while self.monitoring and self.is_connected:
            message = self.midi_in.get_message()
            if message:
                data, delta_time = message
                self.logger.debug(f"Raw MIDI message: {data} (delta: {delta_time:.3f}s)")
                if self.callback:
                    self.callback(data)
            time.sleep(0.001)  # Small sleep to prevent CPU hogging
    
    def find_easypad(self):
        """Try to automatically find and connect to WORLDE EASYPAD.12"""
        for i, port_name in enumerate(self.available_ports):
            if any(keyword in port_name.lower() for keyword in ["easypad", "worlde", "midi", "keyboard"]):
                self.logger.info(f"Found potential device: {port_name}")
                return self.connect_to_device(port_index=i)
        return False, "WORLDE EASYPAD.12 not found"
    
    def handle_direct_input(self, data, message_type, note_or_control, value=None):
        """Map MIDI notes/controls to our button IDs using direct input mapping"""
        str_note = str(note_or_control)
        
        if message_type == "note_on" or message_type == "note_off":
            # Check if we have a mapping for this note
            if str_note in self.direct_input.get("notes", {}):
                mapped_id = self.direct_input["notes"][str_note]
                self.logger.debug(f"Mapped MIDI note {note_or_control} to button ID {mapped_id}")
                return {
                    "type": message_type,
                    "note": mapped_id,
                    "velocity": value,
                    "original_note": note_or_control
                }
        
        elif message_type == "control_change":
            # Check if we have a mapping for this control
            if str_note in self.direct_input.get("controls", {}):
                mapped_id = self.direct_input["controls"][str_note]
                self.logger.debug(f"Mapped MIDI control {note_or_control} to control ID {mapped_id}")
                return {
                    "type": message_type,
                    "control": mapped_id,
                    "value": value,
                    "original_control": note_or_control
                }
        
        # Return the original message if no mapping found
        return None
    
    def parse_midi_message(self, raw_message):
        """Parse raw MIDI message and map to our button IDs"""
        if not raw_message:
            return {"type": "unknown"}
        
        # Basic message parsing
        status_byte = raw_message[0] & 0xF0  # Strip channel
        channel = raw_message[0] & 0x0F
        
        # Load MIDI mapping
        from app.utils import load_midi_mapping
        mapping = load_midi_mapping()
        
        if status_byte == 0x90:  # Note on
            velocity = raw_message[2]
            note = raw_message[1]
            
            # Check if velocity is 0 (note off)
            if velocity == 0:
                return self.parse_midi_message([0x80, note, 64])  # Convert to note off
            
            # Check if this note is mapped to a button ID
            direct_mappings = mapping.get("direct_input", {}).get("note_mappings", {})
            mapped_note = str(note)
            
            if mapped_note in direct_mappings:
                # Return the mapped button ID
                return {
                    "type": "note_on",
                    "note": direct_mappings[mapped_note],
                    "original_note": note,
                    "velocity": velocity,
                    "channel": channel
                }
            
            # If no mapping, just return the note itself as button ID
            return {
                "type": "note_on",
                "note": note,
                "velocity": velocity,
                "channel": channel
            }
            
        elif status_byte == 0x80:  # Note off
            note = raw_message[1]
            velocity = raw_message[2]
            
            # Check if this note is mapped to a button ID
            direct_mappings = mapping.get("direct_input", {}).get("note_mappings", {})
            mapped_note = str(note)
            
            if mapped_note in direct_mappings:
                # Return the mapped button ID
                return {
                    "type": "note_off",
                    "note": direct_mappings[mapped_note],
                    "original_note": note,
                    "velocity": velocity,
                    "channel": channel
                }
            
            # If no mapping, just return the note itself as button ID
            return {
                "type": "note_off",
                "note": note,
                "velocity": velocity,
                "channel": channel
            }
            
        elif status_byte == 0xB0:  # Control change
            control = raw_message[1]
            value = raw_message[2]
            
            # Check if this control is mapped to a button ID
            control_mappings = mapping.get("direct_input", {}).get("control_mappings", {})
            mapped_control = str(control)
            
            if mapped_control in control_mappings:
                # This is a control change that should be treated as a button
                button_id = control_mappings[mapped_control]
                
                # If value > 0, treat as note_on, otherwise note_off
                if value > 0:
                    return {
                        "type": "note_on",
                        "note": button_id,
                        "original_control": control,
                        "velocity": 127,  # Full velocity for control buttons
                        "channel": channel
                    }
                else:
                    return {
                        "type": "note_off",
                        "note": button_id,
                        "original_control": control,
                        "velocity": 0,
                        "channel": channel
                    }
            
            # Regular control change (like slider)
            return {
                "type": "control_change",
                "control": control,
                "value": value,
                "channel": channel
            }
            
        elif status_byte == 0xE0:  # Pitch bend
            lsb = raw_message[1]
            msb = raw_message[2]
            value = (msb << 7) + lsb
            return {
                "type": "pitch_bend",
                "value": value,
                "channel": channel
            }
            
        else:
            # Other MIDI message types we're not handling
            return {
                "type": "unknown",
                "status": status_byte,
                "raw": raw_message
            } 