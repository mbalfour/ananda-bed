"""Async UDP protocol for Ananda bed communication.

This module implements the low-level UDP protocol for communicating with the
Ananda adjustable bed base (Keeson WF02D controller). The protocol was
reverse-engineered from packet captures of the official mobile app.

=============================================================================
CONNECT-ON-DEMAND PATTERN
=============================================================================

The bed firmware only supports ONE active session at a time. If we held a
persistent connection, the user's phone app would be locked out (and vice
versa). To allow coexistence:

    1. Each operation opens a FRESH UDP session (discovery → auth → session)
    2. Performs its work (send command, read status)
    3. Immediately closes the socket

This means every single command or status poll pays the ~1 second handshake
cost, but it ensures the phone app can always connect between our operations.
The 30-second polling interval in the coordinator gives plenty of breathing
room.

=============================================================================
PROTOCOL OVERVIEW
=============================================================================

Connection Handshake (7 packets total):
    1. App → Bed:  Discovery broadcast (contains target MAC + app source port)
    2. Bed → App:  Discovery response (0x1B prefix, confirms bed is present)
    3. App → Bed:  Auth request (16-byte product access key)
    4. Bed → App:  Auth response (0x2B prefix, contains session token bytes)
    5. App → Bed:  Session confirm (echoes session token back)
    6. App → Bed:  Session info request (contains auth token again)
    7. Bed → App:  Session ready (variable length)

Command Packet (30 bytes):
    [0]      0x83           Message type marker
    [1:5]    0x00000019     Payload length (25 bytes, big-endian)
    [5]      session_id     From auth response byte 23
    [6]      session_flag   From auth response byte 24
    [7:9]    seq            16-bit sequence counter (big-endian)
    [9]      0x00           Padding
    [10:23]  FIXED_PAYLOAD  13 fixed protocol bytes
    [23]     motor          Motor command bitmask (continuous)
    [24]     preset         Preset/vibration bitmask (fire-and-forget/cycling)
    [25]     additional     Memory/light bitmask
    [26]     ext            Extended command bitmask (flat)
    [27]     checksum       (0xFA - byte23 - byte24 - byte25 - byte26) & 0xFF
    [28:30]  0xED 0x55      End-of-frame markers

Status Response (44 bytes):
    [0]      0x83           Message type marker
    [29:31]  head_pos       Head position (LE uint16, 0..21138)
    [31:33]  feet_pos       Feet position (LE uint16, 0..8924)
    [33]     head_vib       Head vibration (0=off, 1=low, 3=med, 6=high)
    [34]     feet_vib       Feet vibration (0=off, 1=low, 3=med, 6=high)
    [39]     flags          bit 0=pillow active, bit 4=preset active
"""

import asyncio
import logging
import struct

from .const import BED_PORT, COMMAND_RATE

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fixed protocol constants
# ---------------------------------------------------------------------------

# 13-byte fixed payload that appears in every command packet between the
# session header and the command bytes. Likely encodes protocol version
# and device addressing info. Identical in every packet capture.
FIXED_PAYLOAD = bytes.fromhex("aa03000f000000000100000401")

# Session confirmation packet template (8 bytes).
# Bytes [5:8] are patched with the session token from the auth response.
SESSION_PKT1_TEMPLATE = bytes.fromhex("3300000003b00000")

# Session info request header (8 bytes) + auth token + null terminator.
# Sent as the second part of session setup after the confirm.
SESSION_PKT2_HEADER = bytes.fromhex("730000001403000c")


# ---------------------------------------------------------------------------
# Packet Construction Functions
# ---------------------------------------------------------------------------

def _build_discovery(mac: bytes, source_port: int) -> bytes:
    """Build a 17-byte discovery broadcast packet.

    The bed only responds to discovery if its MAC matches the one in the
    packet. The source_port is embedded so the bed knows where to reply.

    Structure:
        [0:6]   Header (type=0x10, length=12, version=3)
        [6:8]   App's source port (big-endian)
        [8:11]  Flags (0x01 0x00 0x06 -- 0x06 is MAC length prefix)
        [11:17] Target bed MAC address (6 bytes)
    """
    header = bytes.fromhex("100000000c03")
    port_bytes = struct.pack(">H", source_port)
    flags = bytes([0x01, 0x00, 0x06])
    return header + port_bytes + flags + mac


def _build_auth(auth_token: bytes) -> bytes:
    """Build the 29-byte authentication request packet.

    Contains the 16-byte Xlink product access key. The bed validates this
    and returns a session token in its response (bytes 23-25).

    Structure:
        [0:8]    Header (type=0x23, length=24, flags)
        [8:24]   16-byte auth token (product access key)
        [24:29]  Trailer (0x00 0x63 0x00 0x00 0x1E)
    """
    header = bytes.fromhex("230000001803000b")
    trailer = bytes.fromhex("006300001e")
    return header + auth_token + trailer


def _build_command(seq: int, motor: int = 0, preset: int = 0,
                   additional: int = 0, ext: int = 0,
                   session_id: int = 0xB0, session_flag: int = 0x00) -> bytes:
    """Build a 30-byte command packet.

    Args:
        seq: 16-bit monotonically incrementing sequence number
        motor: Byte 23 -- motor command bitmask (continuous, runs while sent)
        preset: Byte 24 -- preset/vibration bitmask (fire-and-forget or cycling)
        additional: Byte 25 -- memory/light bitmask
        ext: Byte 26 -- extended command bitmask (flat)
        session_id: Session token byte from auth response [23]
        session_flag: Session token byte from auth response [24]

    The checksum is a simple subtraction: (0xFA - sum of command bytes) & 0xFF.
    A "stop" packet (all zeros) has checksum 0xFA.
    """
    header = struct.pack(">BI", 0x83, 0x19)
    session = struct.pack(">BBHx", session_id, session_flag, seq)
    checksum = (0xFA - motor - preset - additional - ext) & 0xFF
    trailer = bytes([0xED, 0x55])
    return (header + session + FIXED_PAYLOAD +
            bytes([motor, preset, additional, ext, checksum]) + trailer)


def _parse_status(data: bytes) -> dict | None:
    """Parse a 44-byte status response from the bed.

    The bed sends one of these in response to every command packet. Returns
    None if the packet is too short or doesn't have the expected type marker.

    Parsed fields:
        head_position: uint16 LE at offset 29 (0 = flat, 21138 = fully raised)
        feet_position: uint16 LE at offset 31 (0 = flat, 8924 = fully raised)
        head_vibration: byte at offset 33 (0=off, 1=low, 3=med, 6=high)
        feet_vibration: byte at offset 34 (0=off, 1=low, 3=med, 6=high)
        preset_active: bit 4 of byte 39 (True while bed is executing a preset)
    """
    if len(data) < 44 or data[0] != 0x83:
        return None
    head_pos = struct.unpack_from("<H", data, 29)[0]
    feet_pos = struct.unpack_from("<H", data, 31)[0]
    return {
        "head_position": head_pos,
        "feet_position": feet_pos,
        "head_vibration": data[33],
        "feet_vibration": data[34],
        "preset_active": (data[39] & 0x10) != 0,
    }


# ---------------------------------------------------------------------------
# UDP Session Class
# ---------------------------------------------------------------------------

class AnandaUDPSession:
    """A single UDP session with the bed. Create, use, then close.

    Lifecycle:
        1. Create instance with bed MAC and auth token
        2. Call connect() to perform discovery + auth handshake
        3. Call send_command() / get_status() as needed
        4. Call close() to release the socket

    This class uses asyncio's DatagramTransport for non-blocking UDP I/O,
    which integrates cleanly with Home Assistant's event loop.
    """

    def __init__(self, mac: bytes, auth_token: bytes):
        self._mac = mac
        self._auth_token = auth_token
        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: _AnandaProtocol | None = None
        # Session tokens assigned by the bed during auth -- these MUST be
        # included in every subsequent command packet for the bed to accept it.
        self._session_id = 0xB0       # Default; overwritten by auth response
        self._session_flag = 0x00     # Default; overwritten by auth response
        self._session_extra = 0x00    # Third session byte (usage unclear)
        self._seq = 0                 # Monotonically incrementing packet sequence
        self._bed_addr: tuple[str, int] | None = None  # (ip, port) of discovered bed

    async def connect(self) -> bool:
        """Perform the full connection handshake (discovery + auth + session).

        Returns True on success, False on failure. On failure, the socket is
        already closed -- caller should not retry on the same instance.

        Handshake steps:
            1. Bind UDP socket on any available port
            2. Broadcast discovery packet (bed responds only if MAC matches)
            3. Send auth request with product access key
            4. Receive session token from bed's auth response
            5. Send session confirmation (echo token back)
            6. Send session info request
            7. Drain setup responses and settle
        """
        loop = asyncio.get_running_loop()

        # Create a UDP socket bound to any available port.
        # Broadcast must be enabled for the discovery step.
        transport, protocol = await loop.create_datagram_endpoint(
            _AnandaProtocol, local_addr=("0.0.0.0", 0),
            allow_broadcast=True,
        )
        self._transport = transport
        self._protocol = protocol

        # We need our bound port to embed in the discovery packet
        sock = transport.get_extra_info("socket")
        source_port = sock.getsockname()[1]

        # --- Step 1: Discovery broadcast ---
        # Send to 255.255.255.255:5987. The bed responds with a 0x1B packet
        # if its MAC matches the one in our discovery packet.
        discovery = _build_discovery(self._mac, source_port)
        transport.sendto(discovery, ("255.255.255.255", BED_PORT))

        resp = await protocol.wait_for_response(timeout=3.0)
        if not resp or resp[0][0][0] != 0x1B:
            _LOGGER.error("Ananda bed discovery failed")
            self.close()
            return False

        # Extract the bed's IP from the response source address
        self._bed_addr = (resp[0][1][0], BED_PORT)
        _LOGGER.debug("Bed discovered at %s", self._bed_addr[0])

        # --- Step 2: Authentication ---
        # Send the 16-byte product access key. The bed validates it and
        # returns a 0x2B response containing session tokens at bytes 23-25.
        auth_pkt = _build_auth(self._auth_token)
        transport.sendto(auth_pkt, self._bed_addr)

        resp = await protocol.wait_for_response(timeout=3.0)
        if not resp or resp[0][0][0] != 0x2B:
            _LOGGER.error("Ananda bed auth failed")
            self.close()
            return False

        # Extract session tokens from auth response.
        # These change every connection and MUST be in all command packets.
        data = resp[0][0]
        self._session_id = data[23] if len(data) > 23 else 0xB0
        self._session_flag = data[24] if len(data) > 24 else 0x00
        self._session_extra = data[25] if len(data) > 25 else 0x00

        # --- Step 3: Session confirmation ---
        # Patch the session confirm template with the actual session tokens
        # and send it back to the bed to acknowledge the session.
        confirm = bytearray(SESSION_PKT1_TEMPLATE)
        confirm[5] = self._session_id
        confirm[6] = self._session_flag
        confirm[7] = self._session_extra
        transport.sendto(bytes(confirm), self._bed_addr)
        await asyncio.sleep(0.1)

        # --- Step 4: Session info request ---
        # Contains the auth token again plus a null terminator.
        session_pkt2 = SESSION_PKT2_HEADER + self._auth_token + b'\x00'
        transport.sendto(session_pkt2, self._bed_addr)

        # Drain any remaining handshake responses (heartbeats, device info)
        # and let the connection settle before sending commands.
        await asyncio.sleep(0.5)
        protocol.drain()
        return True

    def _next_seq(self) -> int:
        """Get and increment the 16-bit packet sequence counter."""
        seq = self._seq
        self._seq = (self._seq + 1) & 0xFFFF
        return seq

    async def send_command(self, motor: int = 0, preset: int = 0,
                           additional: int = 0, ext: int = 0) -> dict | None:
        """Send a command and wait for the status response.

        Returns the parsed status dict, or None if no valid response received.
        The bed responds to every command with a 44-byte status packet.
        """
        if not self._transport or not self._bed_addr:
            return None

        # Clear any stale packets from the buffer before sending
        self._protocol.drain()
        pkt = _build_command(self._next_seq(), motor, preset, additional, ext,
                             self._session_id, self._session_flag)
        self._transport.sendto(pkt, self._bed_addr)

        # Wait for the bed's status response
        resp = await self._protocol.wait_for_response(timeout=2.0)
        if resp:
            for data, _ in resp:
                status = _parse_status(data)
                if status:
                    return status
        return None

    async def send_command_no_wait(self, motor: int = 0, preset: int = 0,
                                   additional: int = 0, ext: int = 0) -> None:
        """Send a command without waiting for response.

        Used in motor movement loops where we send commands at 4Hz and don't
        need to process every individual response -- we just need the motor
        to keep running. Status is checked separately between bursts.
        """
        if not self._transport or not self._bed_addr:
            return
        pkt = _build_command(self._next_seq(), motor, preset, additional, ext,
                             self._session_id, self._session_flag)
        self._transport.sendto(pkt, self._bed_addr)

    async def get_status(self) -> dict | None:
        """Poll current status by sending a noop/stop command (all zeros).

        A command with all-zero command bytes is effectively a "poll" -- it
        doesn't move anything but the bed still responds with full status.
        """
        return await self.send_command(0, 0, 0, 0)

    def close(self) -> None:
        """Close the UDP transport, ending the session."""
        if self._transport:
            self._transport.close()
            self._transport = None


# ---------------------------------------------------------------------------
# Asyncio Datagram Protocol
# ---------------------------------------------------------------------------

class _AnandaProtocol(asyncio.DatagramProtocol):
    """Asyncio datagram protocol that buffers received UDP packets.

    This integrates with asyncio's transport/protocol layer to receive
    UDP packets asynchronously. Packets are buffered until explicitly
    consumed via drain() or wait_for_response().
    """

    def __init__(self):
        self._buffer: list[tuple[bytes, tuple]] = []
        self._waiter: asyncio.Future | None = None

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        """Called by asyncio when a UDP packet arrives.

        Buffers the packet and wakes up any coroutine waiting in
        wait_for_response().
        """
        self._buffer.append((data, addr))
        if self._waiter and not self._waiter.done():
            self._waiter.set_result(True)

    def error_received(self, exc: Exception) -> None:
        """Called by asyncio on ICMP errors (e.g., port unreachable)."""
        _LOGGER.debug("UDP error: %s", exc)

    def drain(self) -> list[tuple[bytes, tuple]]:
        """Return and clear all buffered packets.

        Used to discard stale data before sending a new command, or to
        collect all responses after a burst of commands.
        """
        buf = self._buffer
        self._buffer = []
        return buf

    async def wait_for_response(self, timeout: float = 2.0) -> list[tuple[bytes, tuple]] | None:
        """Wait for at least one packet to arrive, then drain the buffer.

        If packets are already buffered, returns immediately. Otherwise,
        blocks until a packet arrives or timeout expires. After the first
        packet arrives, waits an additional 100ms to collect any packets
        that arrive in quick succession (common with UDP).

        Returns None on timeout (no packets received at all).
        """
        if self._buffer:
            return self.drain()
        self._waiter = asyncio.get_running_loop().create_future()
        try:
            await asyncio.wait_for(self._waiter, timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._waiter = None
        # Small delay to collect any additional packets that arrive together
        await asyncio.sleep(0.1)
        return self.drain()


# ---------------------------------------------------------------------------
# High-Level API Functions (used by entities and coordinator)
# ---------------------------------------------------------------------------

async def send_command_and_get_status(
    mac: bytes, auth_token: bytes,
    motor: int = 0, preset: int = 0, additional: int = 0, ext: int = 0,
) -> dict | None:
    """Connect-on-demand: open session, send one command, get status, close.

    This is the primary entry point for single-shot operations (presets,
    status polls, vibration cycles). Each call performs a full handshake,
    which costs ~1 second but ensures we don't block the phone app.

    Used by:
        - coordinator._async_update_data() for periodic polling
        - button.py for preset activation
        - select.py for vibration cycling
        - cover.py for stopping motors
    """
    session = AnandaUDPSession(mac, auth_token)
    try:
        if not await session.connect():
            return None
        status = await session.send_command(motor, preset, additional, ext)
        return status
    finally:
        session.close()


async def run_motor_command(
    mac: bytes, auth_token: bytes, motor_byte: int, duration_sec: float,
) -> dict | None:
    """Open session, run a motor at 4Hz for a fixed duration, then stop.

    Motor commands are "hold to move" -- the motor runs ONLY while command
    packets are being sent at the expected 4Hz rate. Once we stop sending
    (or send a stop/0x00), the motor halts immediately.

    This function sends motor_byte continuously for duration_sec, then sends
    a stop command and returns the final status.

    Used by: button.py for pillow tilt (1-second bursts)
    """
    session = AnandaUDPSession(mac, auth_token)
    try:
        if not await session.connect():
            return None
        end_time = asyncio.get_event_loop().time() + duration_sec
        while asyncio.get_event_loop().time() < end_time:
            await session.send_command_no_wait(motor=motor_byte)
            await asyncio.sleep(COMMAND_RATE)
        # Send stop and get final status
        status = await session.send_command(0, 0, 0, 0)
        return status
    finally:
        session.close()


async def run_motor_to_position(
    mac: bytes, auth_token: bytes, motor_byte: int,
    target_pos: int, is_head: bool, timeout: float = 60.0,
) -> dict | None:
    """Run a motor until the target position (0-100%) is reached or timeout.

    This implements closed-loop position control: we continuously send the
    motor command while monitoring the bed's position feedback in the status
    responses. When the actual position is within 1% of the target, we stop.

    The position comparison converts between HA's 0-100% scale and the bed's
    raw encoder ticks (0..HEAD_MAX or 0..FEET_MAX).

    Note: We read position from response packets received passively between
    commands (the bed sends status after every command packet). This avoids
    needing separate poll commands during movement.

    Used by: cover.py for set_cover_position (move head/feet to exact %)
    """
    from .const import HEAD_MAX, FEET_MAX
    session = AnandaUDPSession(mac, auth_token)
    try:
        if not await session.connect():
            return None
        end_time = asyncio.get_event_loop().time() + timeout
        last_status = None
        while asyncio.get_event_loop().time() < end_time:
            # Send motor command at 4Hz to keep motor running
            await session.send_command_no_wait(motor=motor_byte)
            await asyncio.sleep(COMMAND_RATE)
            # Check position from any status responses that arrived
            self_protocol = session._protocol
            if self_protocol:
                packets = self_protocol.drain()
                for data, _ in packets:
                    status = _parse_status(data)
                    if status:
                        last_status = status
                        pos = status["head_position"] if is_head else status["feet_position"]
                        max_val = HEAD_MAX if is_head else FEET_MAX
                        # Convert target percentage to encoder ticks and check tolerance
                        target_ticks = int(target_pos * max_val / 100)
                        if abs(pos - target_ticks) < max_val * 0.01:
                            # Within 1% of target -- stop the motor
                            await session.send_command(0, 0, 0, 0)
                            return last_status
        # Timeout reached -- stop motor and return best known status
        final = await session.send_command(0, 0, 0, 0)
        return final or last_status
    finally:
        session.close()
