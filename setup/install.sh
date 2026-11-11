#!/bin/sh
# Install DeviceHub as a systemd service (Linux, or Ubuntu/Debian under WSL 2).
#   sudo setup/install.sh            install or update the service, start it
#   sudo setup/install.sh --remove   stop and remove the service (data/ is kept), and the --usb-host rules
#   sudo setup/install.sh --usb-host Linux with NetworkManager, handhelds on a USB cable (USB Network Manager): name the
#                                    cable's interface dhusb<N> (udev) and let DeviceHub's user change NetworkManager
#                                    connections (polkit), so Set up this PC in the editor works. Nothing else changes.
# Without systemd DeviceHub still works: `devhub start` runs the server by hand, and every devhub command
# starts it when it is not running.
set -e

HERE=$(cd "$(dirname "$0")/.." && pwd)
UNIT=/etc/systemd/system/devhub.service
RUN_AS=${SUDO_USER:-$(id -un)}
UDEV_RULE=/etc/udev/rules.d/70-devhub-usb.rules
PK_RULE=/etc/polkit-1/rules.d/49-devhub-networkmanager.rules
PK_PKLA=/etc/polkit-1/localauthority/50-local.d/49-devhub-networkmanager.pkla

remove_usb_host() {
    rm -f "$UDEV_RULE" "$PK_RULE" "$PK_PKLA"
    command -v udevadm >/dev/null && udevadm control --reload 2>/dev/null || true
}

if [ "$1" = "--usb-host" ]; then
    [ "$(id -u)" = 0 ] || { echo "install: run it with sudo (it writes $UDEV_RULE and a polkit rule)" >&2; exit 1; }
    [ "$RUN_AS" != root ] || { echo "install: run it with sudo from your normal account (the one DeviceHub runs as)" >&2; exit 1; }
    if grep -qi microsoft /proc/version 2>/dev/null; then
        echo "install: under WSL the USB cable's adapter belongs to Windows: set it up there" >&2; exit 1
    fi
    command -v nmcli >/dev/null || echo "  warning: nmcli is missing: this needs NetworkManager"
    # USB Ethernet gadgets (Linux g_ether: 0525:a4a1 CDC, 0525:a4a2 RNDIS) get their own name, before systemd's
    # predictable names (80-net-setup-link), so the devicehub-usb profile never takes a phone's USB tethering
    cat > "$UDEV_RULE" <<'RULE'
# DeviceHub: handhelds on a USB cable (USB Network Manager). Written by setup/install.sh --usb-host.
SUBSYSTEM=="net", ACTION=="add", ATTRS{idVendor}=="0525", ATTRS{idProduct}=="a4a[12]", NAME="dhusb%n"
RULE
    udevadm control --reload 2>/dev/null || true
    # polkit: the service runs outside your desktop session, where NetworkManager asks for a password it can't get
    if [ -d /etc/polkit-1/rules.d ] || [ -d /usr/share/polkit-1/rules.d ]; then
        mkdir -p /etc/polkit-1/rules.d
        cat > "$PK_RULE" <<RULE
// DeviceHub: lets $RUN_AS (the DeviceHub service) change NetworkManager connections for USB-cabled handhelds.
// Written by setup/install.sh --usb-host; removed by setup/install.sh --remove.
polkit.addRule(function(action, subject) {
    if (subject.user == "$RUN_AS" && (action.id.indexOf("org.freedesktop.NetworkManager.settings.modify.") == 0 ||
                                      action.id == "org.freedesktop.NetworkManager.network-control"))
        return polkit.Result.YES;
});
RULE
        chmod 644 "$PK_RULE"
    else
        mkdir -p "$(dirname "$PK_PKLA")"
        cat > "$PK_PKLA" <<RULE
[DeviceHub: NetworkManager for USB-cabled handhelds]
Identity=unix-user:$RUN_AS
Action=org.freedesktop.NetworkManager.settings.modify.*;org.freedesktop.NetworkManager.network-control
ResultAny=yes
ResultInactive=yes
ResultActive=yes
RULE
    fi
    echo "USB cable support is set up for $RUN_AS:"
    echo "  $UDEV_RULE        the cable's interface is called dhusb0 (replug the cable if it is in now)"
    echo "  $( [ -f "$PK_RULE" ] && echo "$PK_RULE" || echo "$PK_PKLA")"
    echo "Next: in DeviceHub, Edit the device > Connection > Set up this PC."
    command -v dnsmasq >/dev/null || echo "  note: sharing this PC's internet needs dnsmasq (Arch: pacman -S dnsmasq; Debian/Ubuntu: apt install dnsmasq-base)"
    exit 0
fi

if [ "$1" = "--remove" ]; then
    systemctl disable --now devhub 2>/dev/null || true
    rm -f "$UNIT"
    systemctl daemon-reload
    remove_usb_host
    echo "DeviceHub service removed (settings, devices and passwords stay in $HERE/data)."
    exit 0
fi

fail() { echo "install: $*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || fail "run it with sudo (it writes $UNIT)"
[ "$RUN_AS" != root ] || fail "run it with sudo from your normal account: the service runs as that user, not root"
command -v python3 >/dev/null || fail "python3 is missing (sudo apt install python3)"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 8))' || fail "python3 3.8 or newer is needed"
command -v ssh >/dev/null || fail "ssh is missing (sudo apt install openssh-client)"

if grep -qi microsoft /proc/version 2>/dev/null; then
    echo "WSL detected: device passwords are encrypted with Windows DPAPI (your Windows account)."
    command -v powershell.exe >/dev/null || [ -x /mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe ] ||
        echo "  warning: powershell.exe is not reachable; password devices will not work (key devices do)."
else
    echo "Linux: device passwords are encrypted with openssl and a key in $HERE/data/secret.key."
    command -v openssl >/dev/null || echo "  warning: openssl is missing; password devices need it (sudo apt install openssl)."
fi

if [ ! -d /run/systemd/system ]; then
    echo
    echo "systemd is not running here, so no service is installed."
    if grep -qi microsoft /proc/version 2>/dev/null; then
        echo "Turn it on for WSL: put these two lines in /etc/wsl.conf, then run 'wsl --shutdown' in Windows:"
        echo "    [boot]"
        echo "    systemd=true"
    fi
    echo "Or start the server by hand: $HERE/devhub start"
    exit 1
fi

sed -e "s|@DIR@|$HERE|g" -e "s|@USER@|$RUN_AS|g" -e "s|@PYTHON@|$(command -v python3)|g" \
    "$HERE/setup/devhub.service.in" > "$UNIT"
systemctl daemon-reload
systemctl enable devhub >/dev/null 2>&1
systemctl restart devhub

for i in 1 2 3 4 5 6 7 8 9 10; do
    if python3 -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8765/api/ping", timeout=2)' 2>/dev/null; then
        echo
        echo "DeviceHub is running as $RUN_AS: http://127.0.0.1:8765/"
        echo "Next: add your devices in the web UI, then hook up your agent (see README.md)."
        exit 0
    fi
    sleep 1
done
fail "the service did not answer; see: systemctl status devhub, and $HERE/data/devhubd.log"
