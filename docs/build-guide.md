# Build a card controlled Diwali light board with Raspberry Pi and WLED

Tap a card and a wall sized light board changes animation. Mine spells HAPPY
DIWALI around a ring, a small triangle, and nine diamonds. A Raspberry Pi reads
the cards; a WLED controller drives the pixels. The same RFID reader also
handles music cards through my existing Card Play project.

This guide describes the board I built and the decisions behind it. The first
party run exposed intermittent light card switching, so the revised switching
code described below still needs a long physical test. The companion files
named in the steps below are included in this repository.

## What I used

| Part | My build |
| --- | --- |
| Board | 32 × 40 inch black foam board, gold marker, and a hand reamer |
| Lights | 100 addressable 12 V WS2811 bullet pixels with about 3 inches between bulbs |
| LED controller | GLEDOPTO GL-C-616WL running WLED |
| Power and wiring | 12 V adapter, DC pigtail, lever connector, xConnect pigtail, and an inline fuse on the positive lead |
| Card computer | Raspberry Pi 5, USB keyboard style RFID reader, and six enrolled light cards |
| Existing music system | [Card Play](https://github.com/project-curio/card-play), installed on the Pi |

Use the voltage and wiring requirements of *your* pixels and controller. My
build used a 3 A inline fuse and a conservative WLED current limit; those are
details of this build, not universal values. Size the supply, wire, and fuse
for the actual load. Disconnect wall power before changing any wiring. The
[WLED wiring guide](https://kno.wled.ge/advanced/wiring/) explains fuse
placement and wire sizing; the [GLEDOPTO manual](https://www.gledopto.com/616wl-manual-en.pdf)
shows the controller terminals.

## How the pieces talk

```text
Light card → USB RFID reader → Raspberry Pi → animation frames over the network
                                                    ↓
                                            WLED controller → LED pixels

Music card → same reader → Card Play music backend → speaker
```

The Pi never powers the LED string. It chooses an effect and sends color data
to WLED. The separate 12 V supply powers the pixels through the controller.

## 1. Draw the board and number the pixels

Sketch the lettering and shapes before making holes. Lay the connected string
across the back of the board, starting at its **DATA INPUT** end. Number each
pixel from 1 to 100 in physical wire order and record which numbers belong to
each visible shape. Leave enough slack between neighboring holes before using
the reamer.

| Zone | Pixels used in my design |
| --- | ---: |
| HAPPY | 12 |
| DIWALI | 13 |
| Nine diamonds, four pixels each | 36 |
| Inner circle | 15 |
| Small triangle | 7 |
| **Total visible pixels** | **83** |

The other 17 pixels receive black in every mapped frame. That prevents spare
bulbs along the wire from becoming accidental parts of the drawing. My circle
uses physical bulbs 78–92 and the triangle uses 94–100. Your bulb numbers will
depend on how you route your string, so record your own map rather than copying
mine blindly.

The gold marker gave the words and diamonds a shape when the pixels were off.
Once the lights were on, the gold lettering was harder to read than I expected.
I would test a small white or bright yellow outline under the actual animations
before committing to a permanent lettering finish.

## 2. Mount and wire the lights

Dry fit the string first, then make holes and seat the pixels with the wiring
behind the board. Keep the data arrows moving from the controller toward the
far end of the string. Do not rely on wire color alone; check the labels on
the pixels, pigtail, and controller.

On my controller, the 12 V adapter's positive lead went through an inline fuse
to **INPUT V+**, and its negative lead went to **INPUT V−**. The LED string's
input connected to the controller's **OUTPUT V+**, **IO2** data, and **GND**.
IO2 was the output that worked in my bench test. The Pi used its own power
supply and communicated with WLED over the home network. Confirm the terminal
labels against your exact controller before powering up.

## 3. Configure and test WLED

In WLED's LED settings, I set one WS281x output on GPIO 2 with a length of 100.
I used one segment, ID 0, from Start 0 to Stop 100, with grouping 1, no
spacing or offset, and no reverse or mirror. I kept WLED's automatic current
limit enabled and began at low brightness. The [WLED settings guide](https://kno.wled.ge/features/settings/)
explains the output length, GPIO, and brightness controls.

Before adding cards, use WLED's Solid effect to check the entire string. Then
open `http://YOUR_WLED_IP/json/info` from the Pi's network and confirm WLED
reports 100 LEDs. Use the controller's home network address, not its temporary
setup access point address.

## 4. Build the animations around zones

My Python animation script creates a list of 100 RGB values for every frame.
Each bulb number in the physical map becomes a zero based list index; every
unmapped index stays `(0, 0, 0)`. It sends the frames at 20 frames per second
using WLED's DDP realtime input on UDP port 4048. HTTP is used for setup,
checks, and power control. [WLED documents the DDP port and protocol](https://kno.wled.ge/interfaces/ddp/).

The board has five card selected designs:

| Card | Motion |
| --- | --- |
| Diya | Warm flickering triangle, breathing ruby ring, and gold and ivory words |
| Bloom | Triangle, circle, diamonds, then both words appear in a 10 second loop |
| Orbit | A bright arc moves around the ring and outer petals |
| Sparkle | Sparse glints appear across the outer diamonds |
| Peacock | Colored diamonds open and close like a fan |

I gave each design its own palette. HAPPY and DIWALI use the same repeating
color pattern, and several contrasting colors appear on the board at once.
Bloom is a cumulative reveal: the triangle starts at 0 seconds, the circle at
2, diamonds at 4, and both words at 6. Everything fades out after 9 seconds,
pauses dark, and repeats at 10.

## 5. Test the lights before adding RFID

The companion project files are `diwali_animations.py`, `diwali_rfid.py`,
`test_diwali_animations.py`, `test_diwali_rfid.py`,
`diwali_cards.example.json`, and `diwali-rfid.service`. From the repository
root on your computer, copy them to the Pi:

```sh
ssh PI_USER@PI_HOST 'mkdir -p ~/diwali-lights'
scp diwali_animations.py diwali_rfid.py test_diwali_animations.py test_diwali_rfid.py diwali_cards.example.json diwali-rfid.service PI_USER@PI_HOST:~/diwali-lights/
```

In a Pi terminal, run the following. The animation script uses Python's
standard library. Replace the placeholder with WLED's address on your own
network:

```sh
cd ~/diwali-lights
python3 -B -m unittest -q test_diwali_animations.py
python3 -B diwali_animations.py check --host YOUR_WLED_IP
python3 -B diwali_animations.py map --host YOUR_WLED_IP
python3 -B diwali_animations.py bloom --host YOUR_WLED_IP --seconds 20
```

`map` lights each zone separately. Watch the physical board: a successful API
check or DDP send does not prove that the right bulb lit. A 20 second Bloom
run should show two complete loops and then turn the lights off.

## 6. Add the RFID cards without changing the music player

I already had [Card Play](https://github.com/project-curio/card-play) reading
music cards from a USB RFID reader. For this board, I made a separate
`diwali_rfid.py` process that imports Card Play's installed reader and music
code. The original Card Play source and music card configuration stay intact.
The two services must never own the reader at the same time.

From the same `~/diwali-lights` folder on a Pi desktop session, use the
companion files `diwali_rfid.py`, `test_diwali_rfid.py`,
`diwali_cards.example.json`, and `diwali-rfid.service`.
The service file runs `~/diwali-lights/diwali_rfid.py`, so keep that folder
name unless you update its `ExecStart` path.
With Card Play installed and music cards working, enroll five effect cards and
one Start / Stop card:

```sh
systemctl --user stop curio-player.service
python3 ~/.local/share/curio-player/pi_player.py --enroll
```

Tap each new card, record its complete ID privately, then press Ctrl+C. Restart
`curio-player.service` while preparing the light config:

```sh
systemctl --user start curio-player.service
```

On the first setup only, make a private config from the example and install
the separate user service:

```sh
mkdir -p ~/.config/diwali-lights ~/.config/systemd/user
chmod 700 ~/.config/diwali-lights
cp diwali_cards.example.json ~/.config/diwali-lights/cards.json
nano ~/.config/diwali-lights/cards.json
chmod 600 ~/.config/diwali-lights/cards.json
cp diwali-rfid.service ~/.config/systemd/user/
systemctl --user daemon-reload
```

Replace the placeholders with your card IDs and WLED's home network address.
Do not copy the example over an existing private mapping during a later update.
Keep real IDs outside public source and restrict the config to your Pi user.

To use the combined reader on the Pi:

```sh
python3 -B -m unittest -q test_diwali_animations.py test_diwali_rfid.py
python3 -B diwali_rfid.py --check
systemctl --user stop curio-player.service
systemctl --user start diwali-rfid.service
```

Tap an effect card, then Start / Stop, then a music card. The latest local
revision keeps one animation renderer running as effects change. Start / Stop
pauses it with black frames and resumes the last effect. This revision passed
offline tests but still needs a long test on the actual board.

To return the reader to music only:

```sh
systemctl --user stop diwali-rfid.service
systemctl --user start curio-player.service
```

## 7. Test it like an event, not a desk demo

At the first party, the music cards worked, but some light card changes left
the board dark. The exact cause was not captured: the Pi had no usable journal
for that moment. The earlier light bridge stopped one animation process before
starting the next, so a slow WLED setup request could leave the board dark.
That is a plausible failure path, not a confirmed diagnosis.

Before using the revised code at another event, I would:

1. Alternate among the five effect cards at least 30 times and verify every
   recognized tap changes the board promptly.
2. Test Start / Stop, a music card while lights run, and a Pi reboot followed
   by selecting the combined service again.
3. Leave the intended effect running for at least three hours while checking
   the actual board, not just the service status.
4. If a tap fails, check the private rotating log at
   `~/.local/state/diwali-lights/reader.log` and WLED's `/json/info` endpoint.

The private log records recognized light cards and renderer errors while
redacting card IDs. A running Pi service alone does not mean a card was read
or a frame reached the LEDs.

## Sharing the build

The board design, scripts, examples, and commands can be shared. Keep real
RFID IDs, home IP addresses, SSH details, music paths, and credentials out of
public source and screenshots. The revised switching path has passed offline
tests but still needs a physical endurance test before anyone relies on it at
an event.
