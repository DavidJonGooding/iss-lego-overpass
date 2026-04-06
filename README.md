# ISS Overpass Tracker

A Raspberry Pi project that sits alongside the **Lego ISS 21321** model and lights up when the International Space Station is about to pass over your home.

Three banks of LEDs change colour based on the current pass status, a small OLED display shows the next pass time and elevation, and a buzzer gives you an audible heads-up so you can get outside in time.

---

## How it works

The tracker runs continuously on a Raspberry Pi, calculating ISS pass predictions locally using orbital data fetched from [CelesTrak](https://celestrak.org). No account or API key is needed.

| LED colour | Meaning |
|---|---|
| 🔴 Red | No pass in the next hour - all quiet |
| 🟡 Amber | Pass coming within 60 minutes - time to get ready |
| 🟢 Green | ISS is overhead right now |

The OLED display shows the next pass time, maximum elevation angle, and duration. A higher elevation means a brighter, longer pass - anything above 40° is worth going outside for.

---

## What you'll need

### Hardware

| Item | Notes |
|---|---|
| Raspberry Pi 3B (or any Pi with Wi-Fi) | Any Pi with GPIO and Wi-Fi works |
| 5mm diffused red LEDs × 3 | Diffused lens gives a softer glow |
| 5mm diffused amber/yellow LEDs × 3 | |
| 5mm diffused green LEDs × 3 | |
| 560Ω resistors × 9 | One per LED |
| 0.91" OLED display, 128×32, SSD1306, I2C | The slim form factor suits the plinth well |
| Passive buzzer | Must be passive (not active) - Pi controls the tone via PWM |
| Female-to-female jumper wires | For connecting GPIO to breadboard |
| Breadboard | For prototyping; remove once wiring is finalised |
| Micro USB power supply (5V 2.5A) | For the Pi |
| MicroSD card (8GB+) with Raspberry Pi OS Lite | |

Most of these are available as a bundle - the [Adafruit Parts Pal](https://thepihut.com/products/adafruit-parts-pal) from The Pi Hut covers the LEDs, resistors, and breadboard in one purchase.

### Tools

- Soldering iron (optional but recommended for the final install)
- 3D printer for the plinth (or send the STL files to a print service)

---

## Wiring

All LEDs are wired independently - one GPIO pin per LED, one 560Ω resistor per LED, all cathodes to a common GND rail.

```
GPIO17 ──[560Ω]──► Red LED 1    ──► GND
GPIO27 ──[560Ω]──► Red LED 2    ──► GND
GPIO22 ──[560Ω]──► Red LED 3    ──► GND

GPIO5  ──[560Ω]──► Amber LED 1  ──► GND
GPIO6  ──[560Ω]──► Amber LED 2  ──► GND
GPIO13 ──[560Ω]──► Amber LED 3  ──► GND

GPIO19 ──[560Ω]──► Green LED 1  ──► GND
GPIO26 ──[560Ω]──► Green LED 2  ──► GND
GPIO21 ──[560Ω]──► Green LED 3  ──► GND

GPIO18 ──────────► Buzzer (+)   ──► GND

GPIO2 (SDA) ─────► OLED SDA
GPIO3 (SCL) ─────► OLED SCL
3.3V ────────────► OLED VCC
GND  ────────────► OLED GND
```

All GPIO numbers are BCM (Broadcom) numbering, which is what this project uses throughout.

---

## Software setup

### 1. Prepare your Pi

Flash Raspberry Pi OS Lite to your SD card using [Raspberry Pi Imager](https://www.raspberrypi.com/software/). During setup, configure your Wi-Fi credentials and enable SSH so you can access the Pi headlessly.

Enable I2C for the OLED:

```bash
sudo raspi-config
# Interface Options → I2C → Yes
```

### 2. Clone this repo

```bash
git clone https://github.com/DavidJonGooding/iss-lego-overpass.git
cd iss-lego-overpass
```
 
### 3. Create a virtual environment and install dependencies
 
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
 
### 4. Set your location
 
Open `iss_tracker.py` and edit the coordinates at the top of the file:

```python
LAT = 51.51     # Your latitude  (positive = North)
LON = -0.13      # Your longitude (negative = West)
ALTITUDE_M = 35  # Your altitude in metres above sea level
```

You can find your coordinates from [Google Maps](https://maps.google.com) - right-click your location and the coordinates appear at the top of the context menu. The elevation can be an estimate, but for accurate readings try [this tool](https://www.freemaptools.com/elevation-finder.htm).

### 5. Run it

```bash
source venv/bin/activate
python3 iss_tracker.py
```

You should see the tracker fetch orbital data, calculate upcoming passes, and set the red LEDs. If there is a pass coming within the hour the amber LEDs will be on instead.

---

## Handy shell alias

Add this to `~/.bashrc` so you can start the tracker by just typing `iss`:

```bash
echo "alias iss='cd ~/iss-tracker && source venv/bin/activate && python3 iss_tracker.py'" >> ~/.bashrc
source ~/.bashrc
```

---

## Auto-start on boot (systemd)

Once everything is working, you can make the tracker start automatically whenever the Pi powers on.

Edit `iss-tracker.service` and replace `username` with your Pi username, then:

```bash
sudo cp iss-tracker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable iss-tracker
sudo systemctl start iss-tracker
```

Check it is running:

```bash
sudo systemctl status iss-tracker
journalctl -u iss-tracker -f   # live log output
```

To stop it temporarily (e.g. for other projects on the same Pi):

```bash
sudo systemctl stop iss-tracker
sudo systemctl disable iss-tracker   # also stop it starting on next boot
```

---

## Configuration

All tuneable settings are at the top of `iss_tracker.py`:

| Setting | Default | Description |
|---|---|---|
| `LAT` | 51.51 | Your latitude |
| `LON` | -0.13 | Your longitude |
| `ALTITUDE_M` | 35 | Your altitude in metres |
| `UPCOMING_WINDOW_S` | 3600 | How far ahead to trigger amber (seconds) |
| `MIN_ELEVATION_DEG` | 20 | Ignore passes below this max elevation |
| `POLL_INTERVAL_S` | 3600 | How often to refresh orbital data |

Raising `MIN_ELEVATION_DEG` to 30 or 40 means you will only be alerted to high, good-quality passes - useful if you are in a location with obstructions on the horizon.

---

## [COMING SOON] 3D printed chassis

The `cad/` folder contains everything you need to print the plinth that houses the Pi and electronics, and a simple friction-fit lid.

| File | Description |
|---|---|
| `cad/iss_plinth.stl` | Plinth body - ready to slice and print |
| `cad/iss_plinth_lid.stl` | Lid - ready to slice and print |

**Plinth dimensions:** 135mm × 94mm × 35mm tall. The footprint matches the Lego ISS 21321 display stand precisely - the model sits directly on top.

**Print settings:** PLA, 0.2mm layer height, 3 perimeters, 20% infill. No supports needed for the plinth. The lid can be printed face-up or face-down.

**Key features of the plinth:**
- Pi mounts on four friction-fit snap posts - no screws needed, just press the board down
- OLED window on the front face
- Nine LED holes on the rear face, grouped by colour (red | amber | green)
- Side wall cutouts for USB, ethernet, and power ports

If you do not have a printer, services like [Craftcloud](https://craftcloud3d.com) or a local makerspace can print from the STL files for a few pounds.

---

## Troubleshooting

**OLED not found**
```
WARNING  OLED not found: I2C device not found on address: 0x3C
```
Make sure I2C is enabled (`sudo raspi-config`) and the four OLED wires are correct. Run `i2cdetect -y 1` - you should see `3c` appear in the grid.

**No passes found**
This is normal - there can be gaps of 12–24 hours with no qualifying passes over your location. The tracker searches 48 hours ahead, so it will show upcoming passes even when none are imminent. Check [Heavens-Above](https://heavens-above.com) to verify independently.

**LEDs not lighting**
Double-check the resistor is between the GPIO pin and the LED anode (long leg), and the cathode (short leg) goes to GND. Use a quick Python snippet to test individual pins:
```python
import RPi.GPIO as GPIO
GPIO.setmode(GPIO.BCM)
GPIO.setup(17, GPIO.OUT)
GPIO.output(17, GPIO.HIGH)   # should light red LED 1
```

**Permission error on GPIO**
```bash
sudo usermod -aG gpio $USER
# Log out and back in for the change to take effect
```

---

## Ideas for future development

- **RTL-SDR radio recording** - automatically record the ISS on 145.800 MHz FM during passes using a cheap USB SDR dongle
- **SSTV image capture** - decode slow-scan TV images transmitted by the ISS during special events
- **Web dashboard** - Flask app serving a local page with ground track map and pass history
- **Elevation filter** - only alert for passes above a configurable elevation threshold
- **NeoPixel upgrade** - replace discrete LEDs with a short WS2812B strip for smoother colour transitions

---

## Licence

MIT - do whatever you like with it, and if you build one please share a photo!
