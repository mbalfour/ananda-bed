# Ananda Bed Controller

Control an Ananda adjustable bed base (Keeson WF02D WiFi controller) over your local network.

This project provides:
- **Protocol documentation** for the UDP control protocol
- **Home Assistant integration** for smart home control
- **Command-line tool** for testing and scripting

The protocol was reverse-engineered from packet captures of the official Ananda mobile app. The bed uses a Keeson WF02D WiFi module running the [Xlink IoT platform](https://github.com/xlink-corp/xlink-openapi) SDK, communicating over UDP port 5987.

## Supported Features

| Feature | Supported |
|---------|-----------|
| Head up/down | ✅ |
| Feet up/down | ✅ |
| Pillow tilt up/down | ✅ |
| Presets (Flat, I, II/TV, Zero-G, Anti-Snore) | ✅ |
| Vibration (head/feet/both, 3 levels) | ✅ |
| Position feedback (head %, feet %) | ✅ |
| Vibration state feedback | ✅ |
| Multiple beds | ✅ |
| Light toggle | ⚠️ Unverified |
| Memory position | ⚠️ Unverified |

## Finding Your Bed's MAC Address

You need your bed's 6-byte MAC address to use either the CLI tool or the HA integration. To find it:

1. Look under your bed for a Keeson WF02D wifi module. The MAC address is on the label.
2. In your app, the "bed ID" is the MAC address.

---

## Home Assistant Integration

### Installation

#### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu (top right) → **Custom repositories**
3. Add this repository URL and select category **Integration**
4. Click **Add**, then find "Ananda Bed" in HACS and click **Download**
5. Restart Home Assistant

#### Manual

1. Copy the `custom_components/ananda_bed/` directory to your Home Assistant `config/custom_components/` folder
2. Restart Home Assistant
3. Go to **Settings → Devices & Services → Add Integration**
4. Search for "Ananda Bed"
5. Enter a name, your bed's MAC address (hex string, e.g., `010203040506`), and leave the product access key as default

### Entities Created

For each bed:

- **Cover: Head** -- Position slider (0-100%), open/close/stop
- **Cover: Feet** -- Position slider (0-100%), open/close/stop
- **Button: Flat** -- Move to flat position
- **Button: Preset 1** -- Move to saved preset 1
- **Button: Preset 2** -- Move to saved preset 2
- **Button: Zero Gravity** -- Move to zero-G position
- **Button: Anti-Snore** -- Move to anti-snore position
- **Button: Pillow Up** -- Tilt pillow up (1 second)
- **Button: Pillow Down** -- Tilt pillow down (1 second)
- **Select: Head Vibration** -- Off / Low / Medium / High
- **Select: Feet Vibration** -- Off / Low / Medium / High

### Design Notes

The integration uses a **connect-on-demand** pattern: each command opens a fresh UDP session with the bed, sends the command, reads the status, then disconnects. This allows the phone app and Home Assistant to coexist -- the bed only supports one active session at a time, so there's no persistent connection blocking the app.

The tradeoff is that each command takes ~1-2 seconds (handshake overhead). Motor position commands (set_position on covers) keep the connection open for the duration of movement.

### Multiple Beds

Add the integration multiple times (once per bed) with different MAC addresses.

---

## Command-Line Tool

A standalone Python script for testing and scripting, located in `tools/`.

### Requirements

- Python 3.8+
- No external dependencies (stdlib only)

### Setup

Edit `tools/ananda_controller.py` and replace the placeholder MAC addresses in the `BEDS` dict with your bed's actual MAC:

```python
BEDS = {
    "bed1": bytes([0x06, 0x07, 0xAA, 0xBB, 0xCC, 0xDD]),
}
```

### Usage

```bash
# Move head up for 3 seconds
python3 tools/ananda_controller.py head-up --duration 3

# Move to flat position
python3 tools/ananda_controller.py flat

# Move to zero gravity
python3 tools/ananda_controller.py zerog

# Cycle head vibration (off → low → med → high → off)
python3 tools/ananda_controller.py vibrate-head

# Query current status
python3 tools/ananda_controller.py status

# Control second bed
python3 tools/ananda_controller.py --bed bed2 head-up -d 2

# Override IP (skip discovery)
python3 tools/ananda_controller.py --ip 192.168.1.100 status
```

### All Commands

| Command | Description |
|---------|-------------|
| `head-up` | Raise head (use `--duration`) |
| `head-down` | Lower head (use `--duration`) |
| `feet-up` | Raise feet (use `--duration`) |
| `feet-down` | Lower feet (use `--duration`) |
| `pillow-up` | Tilt pillow up (use `--duration`) |
| `pillow-down` | Tilt pillow down (use `--duration`) |
| `flat` | Move to flat position |
| `preset1` | Move to preset 1 |
| `preset2` | Move to preset 2 (TV) |
| `zerog` | Move to zero gravity |
| `sleep` | Move to anti-snore position |
| `vibrate-head` | Cycle head vibration level |
| `vibrate-feet` | Cycle feet vibration level |
| `vibrate-both` | Cycle both vibration levels |
| `memory1` | Save/recall memory position 1 |
| `light` | Toggle under-bed light |
| `stop` | Stop all motors |
| `status` | Query current position and state |

---

## Protocol Documentation

See [PROTOCOL.md](PROTOCOL.md) for the full reverse-engineered protocol specification, including:

- Frame format and message types
- Discovery and authentication handshake
- Command packet structure (4 command slots)
- Status report decoding (position, vibration, motor state)
- Keepalive mechanism
- Cross-references to the Xlink IoT SDK and Keeson BLE protocol

---

## Related Projects

- [ha-adjustable-bed](https://github.com/kristofferR/ha-adjustable-bed) -- Home Assistant BLE integration for Keeson and other bed brands (same command values, different transport)
- [Xlink IoT SDK](https://github.com/xlink-corp/xlink-openapi) -- The IoT platform SDK this protocol is built on

## License

MIT
