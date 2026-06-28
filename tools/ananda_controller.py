#!/usr/bin/env python3
"""
Ananda Adjustable Bed Base Controller

Controls an Ananda adjustable bed base (Keeson WF02D controller) over its
proprietary UDP protocol on port 5987.

Protocol was reverse-engineered from packet captures of the official mobile app.
See PROTOCOL.md for the full protocol specification.

Usage:
    python3 ananda_controller.py head-up --duration 3
    python3 ananda_controller.py preset1
    python3 ananda_controller.py flat
    python3 ananda_controller.py vibrate-head
    python3 ananda_controller.py status
"""

import argparse
import socket
import struct
import time
import sys

# =============================================================================
# Connection Constants
# =============================================================================

BED_PORT = 5987             # Protocol port (fixed, bed always listens here)
SOCKET_TIMEOUT = 3.0        # Seconds to wait for UDP responses
COMMAND_RATE = 0.25         # Seconds between command packets (4 Hz, matches app behavior)

# Maximum encoder values for percentage calculation (from full-range captures)
HEAD_MAX = 21138            # Encoder ticks when head is fully raised
FEET_MAX = 8924             # Encoder ticks when feet are fully raised

# Known beds on the network, identified by their 6-byte MAC address.
# Replace these with your own bed MAC addresses (found in the app or via packet capture).
BEDS = {
    "bed1": bytes([0x06, 0x07, 0x00, 0x00, 0x00, 0x00]),  # TODO: replace with your bed's MAC
    "bed2": bytes([0x06, 0x07, 0x00, 0x00, 0x00, 0x00]),  # TODO: replace with your bed's MAC
}
DEFAULT_BED = "bed1"

# =============================================================================
# Handshake Packet Construction
#
# Discovery packet structure (17 bytes):
#   [0:5]   10 00 00 00 0c  - Header (type=0x10, length=12)
#   [5]     03              - Protocol version
#   [6:8]   XX XX           - App's source port (big-endian, filled at send time)
#   [8:10]  01 00           - Fixed flags
#   [10:17] device_id       - 7-byte target device ID (to find a specific bed)
#
# The app embeds its source port in the discovery packet so the bed knows
# where to send the response. We use the socket's bound port.
#
# Auth/session packets contain a 16-byte auth token that appears to be the
# same across devices (possibly derived from the app, not the bed).
# =============================================================================

# Xlink product access key -- a static 16-byte shared secret that authorizes local
# LAN control. Same for all units of this product type, hardcoded in firmware and app.
PRODUCT_ACCESS_KEY = bytes.fromhex("4352d88a78aa39750bf70cd6f27bcaa5")

# These are templates -- session_id byte at [5] gets patched after auth
SESSION_PKT1_TEMPLATE = bytes.fromhex("3300000003b00000")
SESSION_PKT2 = bytes.fromhex("730000001403000c") + PRODUCT_ACCESS_KEY + b'\x00'
KEEPALIVE_PKT = bytes.fromhex("d000000002b000")


def build_discovery_packet(mac_address: bytes, source_port: int) -> bytes:
    """
    Build a 17-byte discovery broadcast packet for a specific bed.

    The bed only responds if its MAC matches the one in the packet.
    source_port is embedded so the bed knows where to reply.
    """
    header = bytes.fromhex("100000000c03")
    port_bytes = struct.pack(">H", source_port)
    flags = bytes([0x01, 0x00, 0x06])  # 0x06 = MAC length prefix
    return header + port_bytes + flags + mac_address


def build_auth_packet(access_key: bytes) -> bytes:
    """Build the 29-byte auth request packet."""
    header = bytes.fromhex("230000001803000b")
    trailer = bytes.fromhex("006300001e")
    return header + access_key + trailer

# =============================================================================
# Command Definitions
#
# Commands are sent as 30-byte UDP packets. The packet has 4 "command slots"
# at bytes 23-26. Only one slot is non-zero at a time. The bed responds to
# each command with an ACK and a status report.
#
# Motor commands (byte 23): Continuous commands -- the motor runs while
# packets are being sent, and stops when they stop. Send at ~4Hz.
#
# Preset/vibration commands (byte 24): Presets run until position is reached.
# Vibration commands CYCLE state each time they're sent (off→low→med→high→off).
#
# Extended commands (byte 26): Same behavior as presets.
# =============================================================================

# Motor commands (byte 23) - bitmask values, one bit per motor direction
MOTOR_CMDS = {
    "head-up": 0x01,       # Raise head section
    "head-down": 0x02,     # Lower head section
    "feet-up": 0x04,       # Raise feet section
    "feet-down": 0x08,     # Lower feet section
    "pillow-up": 0x10,     # Tilt pillow section up
    "pillow-down": 0x20,   # Tilt pillow section down
    "stop": 0x00,          # Stop all motors (also the idle/poll command)
}

# Preset and vibration commands (byte 24)
PRESET_CMDS = {
    "preset1": 0x20,       # Saved position preset 1
    "preset2": 0x40,       # Saved position preset 2 (TV position)
    "zerog": 0x10,         # Zero gravity preset position
    "sleep": 0x80,         # Anti-snore / ZZZZ preset position
    "vibrate-head": 0x08,  # Cycle head vibration (off→low→med→high→off)
    "vibrate-feet": 0x04,  # Cycle feet vibration (off→low→med→high→off)
    "vibrate-both": 0x01,  # Cycle both vibration motors together
}

# Additional commands (byte 25) -- from BLE cross-reference, may not be present on all models
ADDITIONAL_CMDS = {
    "memory1": 0x01,       # Save/recall memory position 1
    "light": 0x02,         # Toggle under-bed light
}

# Extended commands (byte 26)
EXTENDED_CMDS = {
    "flat": 0x08,          # Move to fully flat position
}

# Fixed 13-byte payload that sits between the header/session and command bytes.
# This is identical in every command packet -- likely protocol version/addressing.
FIXED_PAYLOAD = bytes.fromhex("aa03000f000000000100000401")


# =============================================================================
# Packet Construction
# =============================================================================

def build_command_packet(seq: int, motor: int = 0x00, preset: int = 0x00,
                         additional: int = 0x00, ext: int = 0x00,
                         session_id: int = 0xB0, session_flag: int = 0x00) -> bytes:
    """
    Build a 30-byte command packet.

    Packet layout:
      [0]      0x83           Message type (command)
      [1:5]    0x00000019     Payload length (25 bytes, little-endian)
      [5]      session_id     Session token from auth response byte 23
      [6]      session_flag   Session token from auth response byte 24
      [7:9]    seq            16-bit big-endian sequence counter
      [9]      0x00           Padding
      [10:23]  FIXED_PAYLOAD  Fixed protocol bytes (13 bytes)
      [23]     motor          Motor command bitmask
      [24]     preset         Preset/vibration command bitmask
      [25]     additional     Memory/light command bitmask
      [26]     ext            Extended command bitmask (flat)
      [27]     checksum       = (0xFA - byte23 - byte24 - byte25 - byte26) & 0xFF
      [28]     0xED           Framing byte
      [29]     0x55           End-of-frame marker

    The checksum is a simple subtraction from 0xFA of the sum of all command
    bytes. This means a STOP packet (all zeros) has checksum 0xFA.
    """
    header = struct.pack(">BI", 0x83, 0x19)
    session = struct.pack(">BBHx", session_id, session_flag, seq)
    checksum = (0xFA - motor - preset - additional - ext) & 0xFF
    trailer = bytes([0xED, 0x55])
    return header + session + FIXED_PAYLOAD + bytes([motor, preset, additional, ext, checksum]) + trailer


# =============================================================================
# Status Parsing
# =============================================================================

def parse_status(data: bytes) -> dict:
    """
    Parse a 44-byte status report from the bed.

    The bed sends these in response to every command packet. Key fields:
      [29:31]  Head motor position (LE uint16, 0=flat, 21138=fully raised)
      [31:33]  Feet motor position (LE uint16, 0=flat, 8924=fully raised)
      [33]     Head vibration level (0=off, 1=low, 3=med, 6=high)
      [34]     Feet vibration level (0=off, 1=low, 3=med, 6=high)
      [39]     Active motor flags:
                 bit 0 (0x01) = pillow tilt motor running
                 bit 4 (0x10) = preset/flat motor running

    Note: There is no absolute position reported for the pillow tilt.
    """
    if len(data) < 44 or data[0] != 0x83:
        return {}
    head_pos = struct.unpack_from("<H", data, 29)[0]
    feet_pos = struct.unpack_from("<H", data, 31)[0]
    head_vib = data[33]  # 0=off, 1=low, 3=med, 6=high
    feet_vib = data[34]  # 0=off, 1=low, 3=med, 6=high
    pillow_active = (data[39] & 0x01) != 0
    preset_active = (data[39] & 0x10) != 0
    return {
        "head_position": head_pos,
        "feet_position": feet_pos,
        "head_vibration": head_vib,
        "feet_vibration": feet_vib,
        "pillow_active": pillow_active,
        "preset_active": preset_active,
    }


def drain_responses(sock: socket.socket, timeout: float = 0.5) -> list:
    """
    Read all pending UDP responses from the socket until timeout.
    Returns a list of raw response byte strings.
    """
    responses = []
    sock.settimeout(timeout)
    while True:
        try:
            data, _ = sock.recvfrom(2048)
            responses.append(data)
        except socket.timeout:
            break
    return responses


# =============================================================================
# Controller Class
# =============================================================================

class AnandaController:
    """
    High-level controller for the Ananda adjustable bed base.

    Handles the connection handshake, command sequencing, and status parsing.
    The bed only accepts one active connection at a time (the app OR this
    controller, not both simultaneously).
    """

    def __init__(self, mac_address=None, ip=None):
        """
        Initialize controller for a specific bed.

        mac_address: 6-byte MAC of the target bed
        ip: override IP (skip discovery and connect directly)
        """
        self.bed_ip = ip  # Will be discovered during handshake if not set
        self.mac_address = mac_address or BEDS[DEFAULT_BED]
        self.auth_token = PRODUCT_ACCESS_KEY
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.settimeout(SOCKET_TIMEOUT)
        # Bind to any available port (we need to know our port for discovery)
        self.sock.bind(("", 0))
        self.source_port = self.sock.getsockname()[1]
        self.seq = 0              # Monotonically incrementing packet sequence number
        self.session_id = 0xB0    # Assigned by bed during handshake (auth response byte 23)
        self.session_flag = 0x00  # Assigned by bed during handshake (auth response byte 24)
        self.session_extra = 0x00 # Assigned by bed during handshake (auth response byte 25)

    def _send(self, data: bytes, addr=None):
        """Send a UDP packet to the bed (or to a broadcast address)."""
        if addr is None:
            addr = (self.bed_ip, BED_PORT)
        self.sock.sendto(data, addr)

    def _recv(self, timeout=SOCKET_TIMEOUT):
        """Receive a single UDP response with timeout. Returns (data, addr) or (b"", None)."""
        self.sock.settimeout(timeout)
        try:
            data, addr = self.sock.recvfrom(2048)
            return data, addr
        except socket.timeout:
            return b"", None

    def handshake(self) -> bool:
        """
        Perform the full 7-packet connection handshake.

        The handshake establishes a session with the bed. The key output is the
        session_id and session_flag (2 bytes), which must be included in every
        subsequent command packet. These change with each new connection.

        Returns True on success, False on failure.
        """
        print("Connecting to bed...")

        # Step 1: Discovery - broadcast to find the bed on the network.
        # The discovery packet contains the bed's device ID; the bed
        # only responds if its ID matches.
        discovery_pkt = build_discovery_packet(self.mac_address, self.source_port)
        self._send(discovery_pkt, ("255.255.255.255", BED_PORT))
        resp, addr = self._recv()
        if not resp or resp[0] != 0x1B:
            # Broadcast may fail on some networks; try unicast directly
            if self.bed_ip:
                print("  Discovery broadcast failed, trying unicast...")
                self._send(discovery_pkt)
                resp, addr = self._recv()
            if not resp or resp[0] != 0x1B:
                print("  ERROR: No discovery response from bed")
                return False
        # Update bed IP from the response source address (handles DHCP changes)
        if addr:
            self.bed_ip = addr[0]
        print(f"  Discovery OK - bed at {self.bed_ip}")

        # Step 2: Authentication - send the 16-byte auth token.
        # The bed validates it and returns a session token in response bytes 23-24.
        auth_pkt = build_auth_packet(self.auth_token)
        self._send(auth_pkt)
        resp, _ = self._recv()
        if not resp or resp[0] != 0x2B:
            print("  ERROR: Auth failed")
            return False
        # Extract the 2-byte session token assigned by the bed.
        # This token changes every connection and must be in all command packets.
        self.session_id = resp[23] if len(resp) > 23 else 0xB0
        self.session_flag = resp[24] if len(resp) > 24 else 0x00
        self.session_extra = resp[25] if len(resp) > 25 else 0x00
        print(f"  Auth OK (session=0x{self.session_id:02x}{self.session_flag:02x}{self.session_extra:02x})")

        # Step 3: Session setup - confirm session and request device info.
        # Patch the session confirm packet with the actual session_id from auth.
        session_confirm = bytearray(SESSION_PKT1_TEMPLATE)
        session_confirm[5] = self.session_id
        session_confirm[6] = self.session_flag
        session_confirm[7] = self.session_extra
        self._send(bytes(session_confirm))
        time.sleep(0.1)
        self._send(SESSION_PKT2)
        resp, _ = self._recv()
        if resp:
            print(f"  Session OK ({len(resp)} bytes)")
        else:
            print("  Session sent (no response, continuing)")

        # Drain any remaining setup responses (heartbeats, etc.)
        drain_responses(self.sock, 0.5)
        time.sleep(0.5)
        print("Connected.\n")
        return True

    def _next_seq(self) -> int:
        """Get and increment the packet sequence counter (wraps at 0xFFFF)."""
        seq = self.seq
        self.seq = (self.seq + 1) & 0xFFFF
        return seq

    def send_command(self, motor: int = 0x00, preset: int = 0x00,
                     additional: int = 0x00, ext: int = 0x00):
        """Build and send a single command packet to the bed."""
        pkt = build_command_packet(self._next_seq(), motor, preset, additional, ext,
                                   self.session_id, self.session_flag)
        self._send(pkt)

    def send_stop(self, count: int = 4):
        """
        Send multiple STOP packets (all command bytes = 0x00).
        Multiple packets ensure delivery over unreliable UDP.
        """
        for _ in range(count):
            self.send_command(0x00, 0x00)
            time.sleep(COMMAND_RATE)

    def run_motor(self, cmd_name: str, duration: float):
        """
        Run a motor command continuously for the specified duration.

        Motor commands are "hold to move" -- the motor runs while command
        packets are being sent at 4Hz, and stops when they stop. After the
        duration, STOP packets are sent to ensure the motor halts.
        """
        motor = MOTOR_CMDS[cmd_name]
        print(f"Sending {cmd_name} for {duration}s...")
        end_time = time.time() + duration
        while time.time() < end_time:
            self.send_command(motor=motor)
            time.sleep(COMMAND_RATE)
        self.send_stop()
        self._print_status()

    def run_preset(self, cmd_name: str, duration: float = 10.0):
        """
        Send a preset command until the bed reaches the target position.

        Presets are "fire and forget" -- the bed moves to a saved position.
        The command is sent repeatedly (like the app does), and we monitor
        status responses to detect when position has stabilized (8 consecutive
        identical readings = arrived). Times out after duration seconds.
        """
        preset = PRESET_CMDS[cmd_name]
        print(f"Sending {cmd_name} for up to {duration}s...")
        end_time = time.time() + duration
        last_status = None
        stable_count = 0

        while time.time() < end_time:
            self.send_command(preset=preset)
            time.sleep(COMMAND_RATE)

            # Check status responses for position stabilization
            responses = drain_responses(self.sock, 0.05)
            for r in responses:
                if len(r) >= 44 and r[0] == 0x83:
                    status = parse_status(r)
                    if status:
                        if last_status and status == last_status:
                            stable_count += 1
                            if stable_count >= 8:
                                print("Position stabilized.")
                                self.send_stop()
                                self._print_status_dict(status)
                                return
                        else:
                            stable_count = 0
                        last_status = status

        self.send_stop()
        self._print_status()

    def run_vibration(self, cmd_name: str):
        """
        Cycle vibration to the next state.

        Vibration commands are STATE TOGGLES -- each burst of commands
        advances the vibration through: off → low → med → high → off.
        One invocation = one state change.
        """
        preset = PRESET_CMDS[cmd_name]
        print(f"Cycling {cmd_name} (low→med→high→off)...")
        for _ in range(8):
            self.send_command(preset=preset)
            time.sleep(COMMAND_RATE)
        self._print_status()

    def run_extended(self, cmd_name: str, duration: float = 10.0):
        """
        Send an extended command (byte 26) until position stabilizes or timeout.
        Same behavior as run_preset but uses the extended command slot.
        """
        cmd_byte = EXTENDED_CMDS[cmd_name]
        print(f"Sending {cmd_name} for up to {duration}s...")
        end_time = time.time() + duration
        last_status = None
        stable_count = 0

        while time.time() < end_time:
            self.send_command(ext=cmd_byte)
            time.sleep(COMMAND_RATE)

            responses = drain_responses(self.sock, 0.05)
            for r in responses:
                if len(r) >= 44 and r[0] == 0x83:
                    status = parse_status(r)
                    if status:
                        if last_status and status == last_status:
                            stable_count += 1
                            if stable_count >= 8:
                                print("Position stabilized.")
                                self.send_stop()
                                self._print_status_dict(status)
                                return
                        else:
                            stable_count = 0
                        last_status = status

        self.send_stop()
        self._print_status()

    def query_status(self):
        """
        Query the current bed state without changing anything.
        Sends a STOP command (which is really just a poll) to get a fresh status.
        """
        print("Querying bed status...")
        self.send_command(0x00, 0x00)
        time.sleep(0.3)
        responses = drain_responses(self.sock, 1.0)
        for r in responses:
            if len(r) >= 44 and r[0] == 0x83:
                self._print_status_dict(parse_status(r))
                return
        # Fallback: try keepalive packet
        self._send(KEEPALIVE_PKT)
        time.sleep(0.5)
        responses = drain_responses(self.sock, 1.0)
        for r in responses:
            if len(r) >= 44 and r[0] == 0x83:
                self._print_status_dict(parse_status(r))
                return
        print("No status response received.")

    def _print_status(self):
        """Drain stale data, send a fresh poll, and print the latest status."""
        drain_responses(self.sock, 0.1)  # Discard buffered stale responses
        self.send_command()              # Send a fresh poll (STOP = poll)
        time.sleep(0.3)                  # Wait for bed to respond
        responses = drain_responses(self.sock, 0.5)
        for r in reversed(responses):    # Use the most recent response
            if len(r) >= 44 and r[0] == 0x83:
                self._print_status_dict(parse_status(r))
                return

    def _print_status_dict(self, status: dict):
        """Format and print a parsed status dictionary."""
        if status:
            VIB_NAMES = {0: "off", 1: "low", 3: "med", 6: "high"}
            head_pct = min(100, round(status['head_position'] / (HEAD_MAX / 100)))
            feet_pct = min(100, round(status['feet_position'] / (FEET_MAX / 100)))
            hv = VIB_NAMES.get(status['head_vibration'], f"?{status['head_vibration']}")
            fv = VIB_NAMES.get(status['feet_vibration'], f"?{status['feet_vibration']}")
            print(f"  Head: {head_pct}% ({status['head_position']})")
            print(f"  Feet: {feet_pct}% ({status['feet_position']})")
            print(f"  Vibration: head={hv} feet={fv}")
            print(f"  Pillow tilt: {'moving' if status['pillow_active'] else 'idle'}")

    def close(self):
        """Close the UDP socket."""
        self.sock.close()


# =============================================================================
# CLI Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Ananda Adjustable Bed Base Controller",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Commands:
  head-up, head-down    Move head motor (use --duration)
  feet-up, feet-down    Move feet motor (use --duration)
  pillow-up, pillow-down Move pillow tilt (use --duration)
  preset1               Preset I
  preset2               Preset II
  zerog                 Zero Gravity position
  sleep                 Anti-snore / ZZZZ position
  flat                  Flat position
  memory1               Save/recall memory position 1
  light                 Toggle under-bed light
  vibrate-head          Cycle head vibration (off→low→med→high→off)
  vibrate-feet          Cycle feet vibration (off→low→med→high→off)
  vibrate-both          Cycle both vibrations (off→low→med→high→off)
  stop                  Stop all motors
  status                Query current position
""",
    )
    parser.add_argument("command", choices=[
        "head-up", "head-down", "feet-up", "feet-down",
        "pillow-up", "pillow-down",
        "preset1", "preset2", "zerog", "sleep",
        "flat",
        "memory1", "light",
        "vibrate-head", "vibrate-feet", "vibrate-both",
        "stop", "status",
    ])
    parser.add_argument("--duration", "-d", type=float, default=1.0,
                        help="Duration in seconds for motor commands (default: 1.0)")
    parser.add_argument("--bed", "-b", choices=list(BEDS.keys()), default=DEFAULT_BED,
                        help=f"Which bed to control (default: {DEFAULT_BED})")
    parser.add_argument("--ip", default=None, help="Override bed IP address")
    args = parser.parse_args()

    # Create controller and connect
    ctrl = AnandaController(mac_address=BEDS[args.bed], ip=args.ip)
    try:
        if not ctrl.handshake():
            sys.exit(1)

        cmd = args.command

        # Route to the appropriate handler based on command type
        if cmd in MOTOR_CMDS and cmd != "stop":
            # Motor commands: continuous send for --duration seconds
            ctrl.run_motor(cmd, args.duration)
        elif cmd in EXTENDED_CMDS:
            # Extended commands (flat): send until position stabilizes
            ctrl.run_extended(cmd)
        elif cmd in ADDITIONAL_CMDS:
            # Additional commands (memory, light): single burst like vibration
            print(f"Sending {cmd}...")
            for _ in range(8):
                ctrl.send_command(additional=ADDITIONAL_CMDS[cmd])
                time.sleep(COMMAND_RATE)
            ctrl._print_status()
        elif cmd in PRESET_CMDS and cmd.startswith("vibrate"):
            # Vibration: single state cycle (off→low→med→high→off)
            ctrl.run_vibration(cmd)
        elif cmd in PRESET_CMDS:
            # Presets: send until position stabilizes
            ctrl.run_preset(cmd)
        elif cmd == "stop":
            # Emergency stop: send many stop packets
            print("Stopping all...")
            ctrl.send_stop(8)
            ctrl._print_status()
        elif cmd == "status":
            # Query only, no movement
            ctrl.query_status()
    except KeyboardInterrupt:
        # Always try to stop motors on interrupt
        print("\nInterrupted, sending stop...")
        ctrl.send_stop()
    finally:
        ctrl.close()


if __name__ == "__main__":
    main()
