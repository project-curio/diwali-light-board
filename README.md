# RFID Diwali Light Board

A Raspberry Pi reads RFID cards and sends animated frames to a WLED controller
that drives a 100-pixel HAPPY DIWALI board. Five cards select Diya, Bloom,
Orbit, Sparkle, or Peacock. A sixth card pauses and resumes the lights. The
same reader can continue to play music through
[Card Play](https://github.com/project-curio/card-play).

The [build guide](docs/build-guide.md) covers the physical design, parts,
wiring, WLED configuration, pixel map, Pi setup, card enrollment, service
switching, and event testing. Start there if you are building your own board.

## What is in this repository

| File | Purpose |
| --- | --- |
| `diwali_animations.py` | Map 100 bulbs into zones and stream five effects to WLED |
| `diwali_rfid.py` | Dispatch light cards while preserving Card Play music cards |
| `diwali_cards.example.json` | Placeholder light-card and WLED configuration |
| `diwali-rfid.service` | Pi user service for the combined reader |
| `deploy_diwali_to_pi.sh` | Optional transfer and service switch helper |
| `test_diwali_*.py` | Offline checks for animation and card logic |

The Python scripts use the standard library. The RFID bridge expects the
installed Card Play runtime at
`~/.local/share/curio-player/pi_player.py` and its music configuration at the
path shown by `python3 diwali_rfid.py --help`. One USB reader can be owned by
only one service at a time: stop `curio-player.service` before starting
`diwali-rfid.service`.

## Try the code

Run the offline tests on your computer:

```sh
python3 -B -m unittest -q test_diwali_animations.py test_diwali_rfid.py
```

On a Pi with WLED configured for the 100-pixel board, try a short animation:

```sh
python3 -B diwali_animations.py check --host YOUR_WLED_IP
python3 -B diwali_animations.py map --host YOUR_WLED_IP
python3 -B diwali_animations.py bloom --host YOUR_WLED_IP --seconds 20
```

Watch the physical LEDs during `map` and Bloom. The API and DDP transport do
not confirm that the intended bulbs lit. See the [build guide](docs/build-guide.md)
for the full sequence and for returning the reader to music only.

## Keep your configuration private

The six card IDs and your WLED home-network address belong in a local config,
never in this repository. Copy `diwali_cards.example.json` to
`~/.config/diwali-lights/cards.json` on the Pi and fill it in there. The
optional deployment helper instead reads `.private/diwali_cards.json` on your
computer; this folder is ignored by Git. Review what `git status` would add
before publishing or sharing screenshots.

If Card Play is already installed on the Pi and you prefer the helper, create
that private file from the example, enter your own IDs and WLED address, then
run the script from the repository root:

```sh
mkdir -p .private
cp diwali_cards.example.json .private/diwali_cards.json
chmod 600 .private/diwali_cards.json
# Edit .private/diwali_cards.json with your own values before continuing.
sh deploy_diwali_to_pi.sh PI_USER@PI_HOST
```

The helper copies the files, checks the private mapping against Card Play,
stops the music-only service, and starts the combined service. If startup
fails, it restores the music-only service. It does not verify physical LED
output; complete the tap and endurance checks in the guide.

## Current verification

An earlier version played Bloom from a physical card. At the first event,
music cards worked but light-card changes sometimes left the board dark. The
revised bridge here switches effects within one renderer and passed offline
tests. It has **not** yet passed a physical long-duration test. For an event,
test rapid card changes and watch the board for the full planned run.

This project is licensed under the [MIT License](LICENSE). Hardware wiring and
power limits depend on your actual components; follow their documentation.
