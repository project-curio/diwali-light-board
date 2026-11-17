#!/bin/sh
# Run in the Mac Terminal. SSH prompts for the Pi password locally.
set -eu

if [ "$#" -ne 1 ]; then
    echo "Usage: sh deploy_diwali_to_pi.sh PI_USER@PI_HOST" >&2
    exit 2
fi

target=$1
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
private_config=$root/.private/diwali_cards.json
if [ ! -f "$private_config" ]; then
    echo "Missing private mapping: $private_config" >&2
    exit 1
fi

ssh "$target" 'mkdir -p ~/diwali-lights ~/.config/diwali-lights ~/.config/systemd/user && chmod 700 ~/.config/diwali-lights'
scp "$root/diwali_animations.py" "$root/diwali_rfid.py" \
    "$root/test_diwali_animations.py" "$root/test_diwali_rfid.py" \
    "$root/diwali-rfid.service" "$target:~/diwali-lights/"
scp "$private_config" "$target:~/.config/diwali-lights/cards.json.new"

ssh "$target" 'sh -s' <<'REMOTE'
set -eu
candidate="$HOME/.config/diwali-lights/cards.json.new"
final="$HOME/.config/diwali-lights/cards.json"
chmod 600 "$candidate"
cd "$HOME/diwali-lights"
python3 -B -m unittest -q test_diwali_animations.py test_diwali_rfid.py
python3 -B diwali_rfid.py --check --lights-config "$candidate"
if [ -f "$final" ]; then
    cp -p "$final" "$final.backup.$(date +%Y%m%d%H%M%S)"
fi
mv "$candidate" "$final"
chmod 600 "$final"
cp "$HOME/diwali-lights/diwali-rfid.service" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user stop curio-player.service
restore_music() {
    systemctl --user stop diwali-rfid.service >/dev/null 2>&1 || :
    systemctl --user start curio-player.service
}
trap restore_music EXIT
systemctl --user start diwali-rfid.service
sleep 2
systemctl --user is-active --quiet diwali-rfid.service
trap - EXIT
systemctl --user status diwali-rfid.service --no-pager
REMOTE
