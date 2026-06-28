# Ananda Bed Base UDP Protocol

## Keeson WF02D Controller -- Port 5987

This document describes the UDP control protocol used by the Ananda adjustable bed base (Keeson WF02D controller). All information is derived from packet captures of the mobile application communicating with the bed.

The protocol is built on the [Xlink IoT platform](https://github.com/xlink-corp/xlink-openapi/blob/master/%E8%AE%BE%E5%A4%87%E7%AB%AF%E5%BC%80%E5%8F%91%E6%96%87%E6%A1%A3/2.%E8%AE%BE%E5%A4%87%E9%80%9A%E8%AE%AF%E5%8D%8F%E8%AE%AE%E8%A7%84%E8%8C%83.md) (云智易, xlink.cn) SDK. The bed's WiFi module identifies itself as "xlink_dev" during handshake. The UDP protocol retains structural similarities to the Xlink serial protocol spec (0x55 end marker, sequence-numbered frames, single-byte checksum, 6-byte MAC addressing) but adapts the framing for UDP transport and uses Keeson-proprietary command bytes for motor/vibration control.

The 4-byte command payload (bytes 23-26) is identical to the Keeson BLE protocol used in their Cool Base product line, documented in the [ha-adjustable-bed](https://github.com/kristofferR/ha-adjustable-bed/blob/master/docs/beds/coolbase.md) Home Assistant integration. The WiFi protocol wraps the same command values in Xlink UDP framing rather than BLE packets.

---

## Table of Contents

1. [Network Overview](#network-overview)
2. [Frame Format](#frame-format)
3. [Message Types](#message-types)
4. [Communication Flow](#communication-flow)
5. [Discovery](#discovery)
6. [Authentication](#authentication)
7. [Session Establishment](#session-establishment)
8. [Command Packets](#command-packets)
9. [Motor Commands](#motor-commands)
10. [Preset and Vibration Commands](#preset-and-vibration-commands)
11. [Additional Commands](#additional-commands-byte-25)
12. [Extended Commands](#extended-commands-byte-26)
13. [Checksum Calculation](#checksum-calculation)
14. [Status Reports](#status-reports)
15. [Keepalive](#keepalive)
16. [Behavioral Notes](#behavioral-notes)
17. [Full Handshake Reference](#full-handshake-reference)

---

## Network Overview

| Property | Value |
|----------|-------|
| Transport | UDP unicast |
| Port | 5987 |
| Bed MAC | `06:07:XX:XX:XX:XX` |
| Bed IP | DHCP-assigned (e.g., 192.168.X.X) |
| mDNS service | `_gosleeping._udp` |
| Discovery | Broadcast to 255.255.255.255:5987 |

The bed obtains its IP via DHCP and advertises itself via mDNS under the service type `_gosleeping._udp`. The app discovers the bed by broadcasting a discovery packet containing the bed's known MAC address.

---

## Frame Format

All messages share a common framing structure:

```
┌──────────┬────────────────────┬─────────────────────────┐
│ Type     │ Length             │ Payload                 │
│ 1 byte   │ 4 bytes (LE)      │ <length> bytes          │
├──────────┼────────────────────┼─────────────────────────┤
│ 0x83     │ 0x19 0x00 0x00 0x00│ ... 25 bytes ...       │
└──────────┴────────────────────┴─────────────────────────┘
```

- **Type** (1 byte): Message type identifier
- **Length** (4 bytes): Little-endian uint32, number of payload bytes that follow
- **Payload** (variable): Message-specific data, exactly `length` bytes

Total packet size = 1 + 4 + length = 5 + length bytes.

---

## Message Types

| Type | Direction | Total Size | Description |
|------|-----------|-----------|-------------|
| `0x10` | App → Broadcast | 17 | Discovery broadcast |
| `0x1B` | Bed → App | 68 | Discovery response |
| `0x23` | App → Bed | 29 | Auth request |
| `0x2B` | Bed → App | 26 | Auth response |
| `0x33` | App → Bed | 8 | ACK / session confirm |
| `0x73` | App → Bed | 25 | Session / device info request |
| `0x5B` | Bed → App | 1025 | Device info response |
| `0x7B` | Bed → App | 12 | Heartbeat |
| `0x83` | App → Bed | 30 | Motor/preset command |
| `0x83` | Bed → App | 44 | Status report |
| `0x8B` | Bed → App | 8 or 14 | Command ACK |
| `0xD0` | App → Bed | 7 | Keepalive request |
| `0xDB` | Bed → App | 14 | Keepalive response |

Note: Type `0x83` is overloaded -- direction and size disambiguate command (30 bytes, app→bed) from status report (44 bytes, bed→app).

---

## Communication Flow

```
    App                                          Bed
     │                                            │
     │──── 0x10 Discovery (broadcast) ──────────►│
     │                                            │
     │◄─── 0x1B Discovery Response ──────────────│
     │                                            │
     │──── 0x23 Auth Request ───────────────────►│
     │                                            │
     │◄─── 0x2B Auth Response ───────────────────│
     │                                            │
     │──── 0x33 Session Confirm ────────────────►│
     │                                            │
     │──── 0x73 Device Info Request ────────────►│
     │                                            │
     │◄─── 0x5B Device Info (1025 bytes) ────────│
     │                                            │
     │         ~1 second delay                    │
     │                                            │
     │◄─── 0x7B Heartbeat ──────────────────────│
     │                                            │
     ├─ ─ ─ Session Established ─ ─ ─ ─ ─ ─ ─ ─ ┤
     │                                            │
     │──── 0x83 Command ────────────────────────►│
     │◄─── 0x8B Command ACK ────────────────────│
     │◄─── 0x83 Status Report ──────────────────│
     │                                            │
     │──── 0x83 Command ────────────────────────►│
     │◄─── 0x8B Command ACK ────────────────────│
     │◄─── 0x83 Status Report ──────────────────│
     │              ...                           │
     │                                            │
     │──── 0xD0 Keepalive ──────────────────────►│
     │◄─── 0xDB Keepalive Response ─────────────│
     │                                            │
```

---

## Discovery

The app broadcasts a discovery packet to `255.255.255.255:5987` containing the target bed's MAC address. The app already knows the MAC from an initial pairing process.

### Discovery Request (0x10) -- 17 bytes

```
10 00 00 00 0c 03 PP PP 01 00 06 06 07 XX XX XX XX
```

| Offset | Bytes | Value | Description |
|--------|-------|-------|-------------|
| 0 | 1 | `0x10` | Message type |
| 1-4 | 4 | `0x0000000C` | Payload length (12) |
| 5 | 1 | `0x03` | Protocol version? |
| 6-7 | 2 | varies | App's UDP source port (big-endian) |
| 8-9 | 2 | `0x01 0x00` | Flags |
| 10 | 1 | `0x06` | MAC address length (6) |
| 11-16 | 6 | `06 07 XX XX XX XX` | Target bed MAC address |

### Discovery Response (0x1B) -- 68 bytes

```
1b 00 00 00 3f 03 00 06 06 07 XX XX XX XX 00 20
31 36 30 66 61 32 62 30 31 35 37 66 35 38 30 30
31 36 30 66 61 32 62 30 31 35 37 66 35 38 30 31
c8 00 cc 17 63 00 00 01 01 00 09 78 6c 69 6e 6b
5f 64 65 76
```

| Offset | Bytes | Value | Description |
|--------|-------|-------|-------------|
| 0 | 1 | `0x1B` | Message type |
| 1-4 | 4 | `0x0000003F` | Payload length (63) |
| 5 | 1 | `0x03` | Protocol version |
| 6 | 1 | `0x00` | Reserved |
| 7 | 1 | `0x06` | MAC length |
| 8-13 | 6 | `06 07 XX XX XX XX` | Bed MAC address |
| 14 | 1 | `0x00` | Separator |
| 15 | 1 | `0x20` | Product credentials length (32) |
| 16-47 | 32 | ASCII `"160fa2b0..."` | Xlink Product ID + Product Key |
| 48-51 | 4 | `C8 00 CC 17` | Device metadata |
| 52 | 1 | `0x63` | Capability flags? |
| 53-56 | 4 | `00 00 01 01` | Version info |
| 57 | 1 | `0x00` | Separator |
| 58 | 1 | `0x09` | Protocol name length (9) |
| 59-67 | 9 | ASCII `"xlink_dev"` | Protocol name |

**Key values extracted:**
- Xlink product credentials: `"160fa2b0157f5800160fa2b0157f5801"` (32 hex ASCII chars, seemingly the same for all units of this product model). Possibly composed of two 16-char halves: Product ID (`160fa2b0157f5800`) and Product Key (`160fa2b0157f5801`), might have been assigned when Keeson registered this product on the Xlink cloud platform.
- Protocol name: `"xlink_dev"`

---

## Authentication

### Auth Request (0x23) -- 29 bytes

```
23 00 00 00 18 03 00 0b 43 52 d8 8a 78 aa 39 75
0b f7 0c d6 f2 7b ca a5 00 63 00 00 1e
```

| Offset | Bytes | Value | Description |
|--------|-------|-------|-------------|
| 0 | 1 | `0x23` | Message type |
| 1-4 | 4 | `0x00000018` | Payload length (24) |
| 5 | 1 | `0x03` | Protocol version |
| 6 | 1 | `0x00` | Reserved |
| 7 | 1 | `0x0B` | Sub-command / request type |
| 8-23 | 16 | `43 52 D8 8A...` | **Product access key** |
| 24 | 1 | `0x00` | Separator |
| 25 | 1 | `0x63` | Flags |
| 26-27 | 2 | `0x00 0x00` | Reserved |
| 28 | 1 | `0x1E` | Terminator |

**Product access key** (16 bytes, static -- seems to be the same for all Ananda beds, probably hardcoded in firmware and app):
```
43 52 D8 8A 78 AA 39 75 0B F7 0C D6 F2 7B CA A5
```

### Auth Response (0x2B) -- 26 bytes

```
2b 00 00 00 15 00 03 00 0b 00 06 06 07 XX XX XX
40 44 28 0d 89 00 64 b0 00 00
```

| Offset | Bytes | Value | Description |
|--------|-------|-------|-------------|
| 0 | 1 | `0x2B` | Message type |
| 1-4 | 4 | `0x00000015` | Payload length (21) |
| 5 | 1 | `0x00` | Status (0 = success) |
| 6 | 1 | `0x03` | Protocol version |
| 7-8 | 2 | `0x00 0x0B` | Sub-command (echoed from request) |
| 9 | 1 | `0x00` | Separator |
| 10 | 1 | `0x06` | MAC length prefix |
| 11-16 | 6 | `06 07 XX XX XX XX` | Bed MAC |
| 17-20 | 4 | varies | Device token (changes per session) |
| 21 | 1 | `0x00` | Reserved |
| 22 | 1 | `0x64` | Constant (100 -- possibly keepalive interval in seconds) |
| 23 | 1 | varies | **Session ID** (use in command byte 5) |
| 24 | 1 | varies | **Session flag** (use in command byte 6) |
| 25 | 1 | `0x00` | Reserved |

---

## Session Establishment

### Session Confirm (0x33) -- 8 bytes

```
33 00 00 00 03 SS FF 00
```

| Offset | Bytes | Value | Description |
|--------|-------|-------|-------------|
| 0 | 1 | `0x33` | Message type |
| 1-4 | 4 | `0x00000003` | Payload length (3) |
| 5 | 1 | varies | **Session ID** (echoed from auth response byte 23) |
| 6 | 1 | varies | **Session flag** (echoed from auth response byte 24) |
| 7 | 1 | `0x00` | Reserved |

### Device Info Request (0x73) -- 25 bytes

```
73 00 00 00 14 03 00 0c 43 52 d8 8a 78 aa 39 75
0b f7 0c d6 f2 7b ca a5 00
```

| Offset | Bytes | Value | Description |
|--------|-------|-------|-------------|
| 0 | 1 | `0x73` | Message type |
| 1-4 | 4 | `0x00000014` | Payload length (20) |
| 5 | 1 | `0x03` | Protocol version |
| 6 | 1 | `0x00` | Reserved |
| 7 | 1 | `0x0C` | Request sub-type |
| 8-23 | 16 | Product access key | Same 16-byte product access key |
| 24 | 1 | `0x00` | Terminator |

### Device Info Response (0x5B) -- 1025 bytes

A large response (payload length 1020) containing device metadata. Mostly zero-padded. Contains the `"xlink_dev"` protocol string. Exact structure is not fully decoded but is not required for basic control.

### Heartbeat (0x7B) -- 12 bytes

Sent by the bed approximately 1 second after session establishment, and periodically thereafter.

```
7b 00 00 00 07 00 0c 00 00 cd ed XX
```

| Offset | Bytes | Value | Description |
|--------|-------|-------|-------------|
| 0 | 1 | `0x7B` | Message type |
| 1-4 | 4 | `0x00000007` | Payload length (7) |
| 5 | 1 | `0x00` | Reserved |
| 6 | 1 | `0x0C` | Sub-command (matches auth request type) |
| 7-8 | 2 | `0x00 0x00` | Reserved |
| 9-10 | 2 | `0xCD 0xED` | Fixed marker |
| 11 | 1 | varies | Session-specific value (not a checksum) |

---

## Command Packets

### Command (0x83) -- 30 bytes, App → Bed

This is the primary control message. Sent at ~4 Hz while a button is held.

```
Byte:  0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29
      83 19 00 00 00 B0 00 SS SS 00 AA 03 00 0F 00 00 00 00 01 00 00 04 01 MC PC 00 00 CK ED 55
```

| Offset | Size | Value | Description |
|--------|------|-------|-------------|
| 0 | 1 | `0x83` | Message type |
| 1-4 | 4 | `0x00000019` (LE) | Payload length (25 bytes) |
| 5 | 1 | varies | **Session ID** (from auth response byte 23) |
| 6 | 1 | varies | **Session flag** (from auth response byte 24) |
| 7-8 | 2 | varies | **Sequence counter** (big-endian uint16) |
| 9 | 1 | `0x00` | Reserved |
| 10 | 1 | `0xAA` | Marker byte |
| 11-12 | 2 | `0x03 0x00` | Fixed |
| 13 | 1 | `0x0F` | Fixed |
| 14-17 | 4 | `0x00000000` | Reserved |
| 18 | 1 | `0x01` | Active flag (1 = active command) |
| 19-20 | 2 | `0x00 0x00` | Reserved |
| 21 | 1 | `0x04` | Command class |
| 22 | 1 | `0x01` | Sub-class |
| 23 | 1 | varies | **Motor command** (bitmask) |
| 24 | 1 | varies | **Preset/vibration command** (bitmask) |
| 25 | 1 | `0x00` | Reserved |
| 26 | 1 | varies | **Extended command** (bitmask) |
| 27 | 1 | varies | **Checksum** |
| 28 | 1 | `0xED` | Framing byte |
| 29 | 1 | `0x55` | End-of-frame marker |

### Sequence Counter (bytes 7-8)

- 16-bit big-endian unsigned integer
- Monotonically incrementing across the entire session
- Wraps at 0xFFFF → 0x0000
- Increments by 1 per command packet sent

---

## Motor Commands

Byte 23 is a bitmask controlling motor movement:

| Bit | Hex | Action |
|-----|-----|--------|
| 0 | `0x01` | Head Up |
| 1 | `0x02` | Head Down |
| 2 | `0x04` | Feet Up |
| 3 | `0x08` | Feet Down |
| 4 | `0x10` | Pillow Tilt Up |
| 5 | `0x20` | Pillow Tilt Down |
| - | `0x00` | Stop all motors |

Bits can be combined for simultaneous motor activation (e.g., `0x05` = Head Up + Feet Up).

---

## Preset and Vibration Commands

Byte 24 is a bitmask controlling presets and vibration:

| Bit | Hex | Action |
|-----|-----|--------|
| 0 | `0x01` | Both vibration motors ON |
| 2 | `0x04` | Bottom (feet) vibration ON |
| 3 | `0x08` | Top (head) vibration ON |
| 4 | `0x10` | Zero Gravity preset |
| 5 | `0x20` | Preset I |
| 6 | `0x40` | Preset II (TV position) |
| 7 | `0x80` | ZZZZ (Anti-snore / sleep preset) |
| - | `0x00` | Stop / Off |

**Notes:**
- Vibration bits `0x04` and `0x08` select individual motors; `0x01` activates both simultaneously
- Presets trigger a macro movement sequence; the bed moves to the target position autonomously
- Send preset command once; the bed handles the movement internally

---

## Additional Commands (Byte 25)

Byte 25 controls memory presets and lighting (from BLE protocol cross-reference, not yet verified over WiFi):

| Hex | Action |
|-----|--------|
| `0x01` | Memory preset 1 (save/recall) |
| `0x02` | Light toggle (under-bed light) |
| `0x04` | Memory preset 2 (some models) |

---

## Extended Commands (Byte 26)

Byte 26 is used for additional commands:

| Hex | Action |
|-----|--------|
| `0x04` | Massage level cycle (from BLE cross-reference, unverified over WiFi) |
| `0x08` | Flat position |

### Example

```
Flat: 83 00 00 00 19 56 01 00 14 00 AA 03 00 0F 00 00 00 00 01 00 00 04 01 00 00 00 08 F2 ED 55
```

---

## Checksum Calculation

The checksum at byte 27 is calculated as:

```
checksum = (0xFA - byte[23] - byte[24] - byte[25] - byte[26]) & 0xFF
```

Where:
- `byte[23]` = motor command bitmask
- `byte[24]` = preset/vibration bitmask
- `byte[25]` = reserved (always 0x00)
- `byte[26]` = extended command bitmask

### Examples

| Motor (byte 23) | Preset (byte 24) | Extended (byte 26) | Checksum (byte 27) |
|-----------------|-------------------|---------------------|---------------------|
| `0x00` (stop) | `0x00` (off) | `0x00` | `0xFA` |
| `0x01` (head up) | `0x00` | `0x00` | `0xF9` |
| `0x02` (head down) | `0x00` | `0x00` | `0xF8` |
| `0x04` (feet up) | `0x00` | `0x00` | `0xF6` |
| `0x08` (feet down) | `0x00` | `0x00` | `0xF2` |
| `0x00` | `0x10` (zero-g) | `0x00` | `0xEA` |
| `0x00` | `0x20` (Preset I) | `0x00` | `0xDA` |
| `0x00` | `0x01` (vibrate) | `0x00` | `0xF9` |
| `0x00` | `0x00` | `0x08` (flat) | `0xF2` |

---

## Status Reports

### Status Report (0x83) -- 44 bytes, Bed → App

Sent by the bed in response to each command, reporting current position and state.

| Offset | Size | Value | Description |
|--------|------|-------|-------------|
| 0 | 1 | `0x83` | Message type |
| 1-4 | 4 | `0x00000027` (LE) | Payload length (39) |
| 5-12 | 8 | `00 06 06 07 XX XX XX XX` | Device identifier (includes MAC) |
| 13-14 | 2 | varies | Status sequence counter (big-endian) |
| 15-16 | 2 | `0x00 0xAA` | Marker |
| 17 | 1 | `0x83` | Sub-type |
| 18-19 | 2 | `0x00 0x17` | Inner payload length (23) |
| 20-22 | 3 | `0x00 0x00 0x00` | Reserved |
| 23 | 1 | varies | **Movement state** (see below) |
| 24 | 1 | `0x00` | Reserved |
| 25 | 1 | varies | Incrementing sub-counter |
| 26-28 | 3 | `0x0A 0x0C 0x01` | Fixed |
| 29-30 | 2 | varies | **Head motor position** (LE uint16) |
| 31-32 | 2 | varies | **Feet motor position** (LE uint16) |
| 33 | 1 | varies | **Head vibration level** |
| 34 | 1 | varies | **Feet vibration level** |
| 35-36 | 2 | varies | Vibration timer (decrementing) |
| 37-38 | 2 | `0x00 0x00` | Reserved |
| 39 | 1 | varies | **Active motor flags** |
| 40 | 1 | varies | Vibration active (`0x01`=on, `0xFF`=off) |
| 41-42 | 2 | varies | Checksum / counter |
| 43 | 1 | `0x55` | End-of-frame marker |

### Motor Position Values

Positions are encoder ticks (little-endian uint16):

| Motor | Flat (min) | Fully Raised (max) |
|-------|-----------|-------------------|
| Head | 0 | ~21138 |
| Feet | 0 | ~8924 |

### Vibration Level (bytes 33, 34)

| Value | Level |
|-------|-------|
| `0x00` | Off |
| `0x01` | Low |
| `0x03` | Medium |
| `0x06` | High |

Vibration is cycled by repeatedly sending the vibration command: off → low → med → high → off.

### Active Motor Flags (byte 39)

| Bit | Meaning |
|-----|---------|
| `0x01` | Pillow tilt motor active |
| `0x10` | Preset/flat motor active |

Note: No absolute position is reported for the pillow tilt motor.

### Movement State (byte 23)

Changes during active motor movement. Approximate meaning:

- `0x30`-`0x3A`: Idle or slow transitions
- Lower values (e.g., `0x2E`-`0x2F`): Rapid movement in progress

---

## Keepalive

Keepalive packets maintain the UDP session when no commands are being sent.

### Keepalive Request (0xD0) -- 7 bytes, App → Bed

```
d0 00 00 00 02 b0 00
```

| Offset | Size | Value | Description |
|--------|------|-------|-------------|
| 0 | 1 | `0xD0` | Message type |
| 1-4 | 4 | `0x00000002` | Payload length (2) |
| 5 | 1 | `0xB0` | Sub-type marker |
| 6 | 1 | `0x00` | Reserved |

### Keepalive Response (0xDB) -- 14 bytes, Bed → App

```
db 00 00 00 08 00 06 06 07 XX XX XX XX 00
```

| Offset | Size | Value | Description |
|--------|------|-------|-------------|
| 0 | 1 | `0xDB` | Message type |
| 1-4 | 4 | `0x00000008` | Payload length (8) -- **NOTE: actual remaining = 9** |
| 5 | 1 | `0x00` | Status |
| 6 | 1 | `0x06` | MAC length |
| 7-12 | 6 | `06 07 XX XX XX XX` | Bed MAC |
| 13 | 1 | `0x00` | Terminator |

---

## Behavioral Notes

### Command Transmission

- Commands are sent continuously at approximately **4 Hz** (~250 ms interval) while a button is held
- On button release, multiple **STOP** packets (`motor=0x00, preset=0x00`) are sent to compensate for UDP packet loss
- The sequence counter increments by 1 per packet across the entire session lifetime
- There is no retransmission mechanism -- reliability is achieved through repetition

### Session Lifecycle

1. Discovery via broadcast identifies the bed's current IP
2. Authentication uses a pre-shared 16-byte token (established during initial pairing)
3. Session confirm (`0x33`) and device info request (`0x73`) complete the handshake
4. After ~1 second, the bed sends a heartbeat (`0x7B`) indicating readiness
5. Commands can then be sent freely
6. Keepalives should be sent periodically during idle periods to maintain the session

### Command ACK (0x8B)

The bed acknowledges each command with a type `0x8B` packet (8 or 14 bytes). The variable size suggests the ACK may include additional state in some cases. The ACK confirms receipt but does not need to be processed for basic control.

### Error Handling

- No explicit error messages have been observed in captures
- If the bed does not respond to discovery, re-broadcast
- If authentication fails, the bed simply does not respond
- Lost command packets are compensated by continuous transmission
- If the session becomes stale, restart from discovery

---

## Full Handshake Reference

Complete raw hex dump of a successful session establishment:

### Step 1: Discovery (App → Broadcast:5987)
```
10 00 00 00 0c 03 PP PP 01 00 06 06 07 XX XX XX XX
```

### Step 2: Discovery Response (Bed → App)
```
1b 00 00 00 3f 03 00 06 06 07 XX XX XX XX 00 20
31 36 30 66 61 32 62 30 31 35 37 66 35 38 30 30
31 36 30 66 61 32 62 30 31 35 37 66 35 38 30 31
c8 00 cc 17 63 00 00 01 01 00 09 78 6c 69 6e 6b
5f 64 65 76
```

### Step 3: Auth Request (App → Bed)
```
23 00 00 00 18 03 00 0b 43 52 d8 8a 78 aa 39 75
0b f7 0c d6 f2 7b ca a5 00 63 00 00 1e
```

### Step 4: Auth Response (Bed → App)
```
2b 00 00 00 15 00 03 00 0b 00 06 06 07 XX XX XX
40 44 28 0d 89 00 64 b0 00 00
```

### Step 5: Session Confirm (App → Bed)
```
33 00 00 00 03 SS FF 00    (SS=session_id, FF=session_flag from auth response)
```

### Step 6: Device Info Request (App → Bed)
```
73 00 00 00 14 03 00 0c 43 52 d8 8a 78 aa 39 75
0b f7 0c d6 f2 7b ca a5 00
```

### Step 7: Device Info Response (Bed → App)
```
5b [1020 bytes payload - mostly zeros, contains "xlink_dev"]
```
(1025 bytes total)

### Step 8: Heartbeat (Bed → App, ~1 second later)
```
7b 00 00 00 07 00 0c 00 00 cd ed XX    (XX varies per session)
```

### Step 9: Begin Command Transmission
```
83 19 00 00 00 b0 00 00 01 00 aa 03 00 0f 00 00
00 00 01 00 00 04 01 XX YY 00 00 ZZ ed 55
```
Where XX=motor, YY=preset, ZZ=checksum.

---

## Implementation Checklist

For a minimal controller implementation:

1. **Discover bed**: Broadcast `0x10` packet with known MAC to port 5987
2. **Parse response**: Extract bed IP from UDP source address of `0x1B` reply
3. **Authenticate**: Send `0x23` with 16-byte product access key
4. **Confirm session**: Wait for `0x2B`, then send `0x33` confirm
5. **Request device info**: Send `0x73` (include product access key)
6. **Wait for heartbeat**: Bed sends `0x7B` when ready (~1 sec)
7. **Send commands**: Construct `0x83` packets at ~4 Hz with correct checksum
8. **Send stops**: Multiple stop packets on command release
9. **Keepalive**: Send `0xD0` periodically during idle to maintain session
10. **Parse status**: Read `0x83` responses (44 bytes) for motor positions

---

## Revision History

| Date | Notes |
|------|-------|
| 2026-06-27 | Initial protocol documentation from packet captures |
