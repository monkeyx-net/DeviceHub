#!/usr/bin/env python3
"""USB-tethered devices (USB Network Manager), with no device: the wrapper script DeviceHub sends runs locally against
stand-in copies of USB_Network_Manager.sh. Run on Linux/WSL: python3 tests/usbnet.py"""
import os, subprocess, sys, tempfile

os.environ["DEVHUB_DATA"] = tempfile.mkdtemp()
os.environ.setdefault("DEVHUB_PLATFORM", "linux")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import devhubd as h

DEV = "g350"
T = tempfile.mkdtemp()
checks = 0


def expect(what, got, want):
    global checks
    checks += 1
    if got != want:
        sys.exit("FAIL: %s: got %r, want %r" % (what, got, want))


def stand_in(name, body):
    p = os.path.join(T, name)
    with open(p, "w") as f:
        f.write("#!/bin/bash\n" + body)
    return p


# a current script: answers like USB Network Manager 1.5+ (gateway/ip from $FAKE_GW/$FAKE_IP, args logged)
NEW = stand_in("new.sh", 'echo "$*" >> "%s/calls"\ncase "$1" in\n'
               '  --refresh-net) echo "gateway=${FAKE_GW:-192.168.7.1} ip=${FAKE_IP:-192.168.7.2}" ;;\n'
               '  --set-gateway) echo "gateway=$2 ip=usb0" ;;\n'
               '  *) echo "would draw the dashboard"; exit 9 ;;\nesac\n' % T)
OLD = stand_in("old.sh", 'echo "dashboard" > "%s/old-ran"\n' % T)     # no command-line modes
FAIL = stand_in("fail.sh", '# --refresh-net\necho "sudo: a password is required"; exit 1\n')
calls = os.path.join(T, "calls")


def local_ssh(d, cmd, inp=None, timeout=20):
    p = subprocess.run(["sh", "-c", cmd], input=inp, capture_output=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


h.ssh_run = local_ssh
h.save_devices = lambda: None


def setup(host="192.168.7.2", script=NEW, **kw):
    d = dict(h.DEVICE_DEFAULTS, id=DEV, name="G350", host=host, cfw="dArkOS", user="ark", usb_net=True,
             usb_script=script, smb="\\\\%s\\roms" % host, **kw)
    h.H.devices = {DEV: d}
    h.H.rt = {}
    if os.path.exists(calls):
        os.unlink(calls)
    return d


def ran():
    try:
        return open(calls).read().split("\n")[:-1]
    except FileNotFoundError:
        return []


# addresses
expect("other address of .7.2", h.usb_alt("192.168.7.2"), "192.168.137.2")
expect("other address of .137.2", h.usb_alt("192.168.137.2"), "192.168.7.2")
expect("a LAN address has none", h.usb_alt("192.168.1.50"), None)
expect("PC end with sharing on", h.usb_pc_ip("192.168.137.2"), "192.168.137.1")
expect("PC end of a LAN address: none", h.usb_pc_ip("192.168.1.50"), None)

# the editor's fields
expect("usb fields saved", {k: h.clean_device({"id": "x", "host": "192.168.7.2", "usb_net": "on",
                                               "usb_script": "/roms/tools/USB_Network_Manager.sh"})[k]
                            for k in ("usb_net", "usb_script")},
       {"usb_net": True, "usb_script": "/roms/tools/USB_Network_Manager.sh"})
try:
    h.clean_device({"id": "x", "host": "192.168.7.2", "usb_script": "x; reboot"})
    expect("a script path with shell characters is refused", "accepted", "refused")
except h.ApiError:
    expect("a script path with shell characters is refused", "refused", "refused")

# --refresh-net
d = setup()
ok, msg = h.usb_run(DEV, d)
expect("refresh: ok", ok, True)
expect("refresh: message", msg, "default route via 192.168.7.1 (device 192.168.7.2)")
expect("refresh: the script got --refresh-net", ran(), ["--refresh-net"])
expect("refresh: route recorded", h.rt(DEV)["usb"]["gateway"], "192.168.7.1")

# --set-gateway, and a bad gateway never reaches the device
d = setup()
ok, msg = h.usb_run(DEV, d, "192.168.137.1")
expect("set-gateway: ok", (ok, ran()), (True, ["--set-gateway 192.168.137.1"]))
expect("set-gateway: device shown only when it is an address", msg, "default route via 192.168.137.1")
d = setup()
try:
    h.usb_run(DEV, d, "1.2.3.4; reboot")
    expect("bad gateway refused", "accepted", "refused")
except h.ApiError:
    expect("bad gateway refused, nothing run", ran(), [])

# the PC answers no ping: DeviceHub sets the route through the PC end it reaches the device by
d = setup("192.168.137.2")
os.environ.update(FAKE_GW="192.168.7.1", FAKE_IP="unknown")
ok, msg = h.usb_run(DEV, d)
del os.environ["FAKE_GW"], os.environ["FAKE_IP"]
expect("no ping: falls back to --set-gateway", ran(), ["--refresh-net", "--set-gateway 192.168.137.1"])
expect("no ping: route through the PC", (ok, h.rt(DEV)["usb"]["gateway"]), (True, "192.168.137.1"))

# a copy without the command-line modes is never run (it would take over the screen)
d = setup(script=OLD)
ok, msg = h.usb_run(DEV, d)
expect("old script: refused", (ok, "1.5.0" in msg), (False, True))
expect("old script: not run", os.path.exists(os.path.join(T, "old-ran")), False)

# not on the device (a path that does not exist, and none in the usual folders on this machine)
d = setup(script="/nonexistent/USB_Network_Manager.sh")
ok, msg = h.usb_run(DEV, d)
expect("missing script", (ok, msg.startswith("USB_Network_Manager.sh not found")), (False, True))

# the script fails
d = setup(script=FAIL)
ok, msg = h.usb_run(DEV, d)
expect("failing script: its last line", (ok, msg), (False, "USB Network Manager exited 1: sudo: a password is required"))

# upkeep: a new shared connection refreshes once; later only when the route points elsewhere, at most every 5 min
d = setup()
h.usb_upkeep(DEV, d, 111)
h.usb_upkeep(DEV, d, 111)
expect("new connection: one refresh", ran(), ["--refresh-net"])
h.rt(DEV)["status"] = {"gw": "192.168.137.1"}
h.usb_upkeep(DEV, d, 111)
expect("wrong route, just refreshed: waits", ran(), ["--refresh-net"])
h.rt(DEV)["usb_try"] -= h.USB_RETRY_S
h.usb_upkeep(DEV, d, 111)
expect("wrong route, retry time passed: refreshed", ran(), ["--refresh-net", "--refresh-net"])
h.rt(DEV)["usb_try"] -= h.USB_RETRY_S
h.rt(DEV)["status"] = {"gw": "192.168.7.1"}
h.usb_upkeep(DEV, d, 111)
expect("route right: nothing run", len(ran()), 2)
h.usb_upkeep(DEV, d, 222)
expect("reconnected: refreshed again", len(ran()), 3)

# the PC switched internet sharing: the device answers at its other address, and the SMB path follows
d = setup()
nd = h.usb_move(DEV, d, "192.168.137.2")
expect("moved", (nd["host"], h.H.devices[DEV]["host"], nd["smb"]), ("192.168.137.2", "192.168.137.2", "\\\\192.168.137.2\\roms"))

# the status probe reports the default route (from /proc/net/route, little-endian hex)
st = h.parse_status("gw=0107A8C0\nos=dArkOS\n", d)
expect("probe gateway", st["gw"], "192.168.7.1")
expect("probe: no default route", h.parse_status("gw=\n", d)["gw"], "")
expect("probe asks for the route only on USB devices",
       ("USB=1" in h.probe_script(d), "USB=1" in h.probe_script(dict(d, usb_net=False))), (True, False))

# ---- this PC's end (Linux + NetworkManager), with a stand-in nmcli that keeps the profile in a file
BIN = os.path.join(T, "bin")
os.makedirs(BIN)
NM = os.path.join(T, "nm-profile")
NMLOG = os.path.join(T, "nmcli-calls")
with open(os.path.join(BIN, "nmcli"), "w") as f:
    f.write("""#!/bin/sh
echo "$*" >> "%(log)s"
[ -n "$NM_DENY" ] && [ "$1" = connection ] && { echo "Error: Failed: Insufficient privileges" >&2; exit 1; }
case "$*" in
  "-t -f RUNNING general") echo running ;;
  "-t -g ipv4.method,ipv4.addresses connection show devicehub-usb")
    [ -f "%(nm)s" ] || { echo "Error: devicehub-usb - no such connection profile." >&2; exit 10; }; cat "%(nm)s" ;;
  "connection add"*|"connection modify"*)
    case "$*" in *"ipv4.method shared"*) printf 'shared\n192.168.137.1/24\n' ;; *) printf 'manual\n192.168.7.1/24\n' ;; esac > "%(nm)s" ;;
  "connection delete devicehub-usb") rm -f "%(nm)s" ;;
esac
""" % {"log": NMLOG, "nm": NM})
for n in ("nmcli", "dnsmasq"):
    if n == "dnsmasq":
        open(os.path.join(BIN, n), "w").write("#!/bin/sh\n")
    os.chmod(os.path.join(BIN, n), 0o755)
os.environ["PATH"] = BIN + os.pathsep + os.environ["PATH"]
h.PLATFORM = "linux"
udev, pk = os.path.join(T, "udev.rules"), os.path.join(T, "pk.rules")
h.USBHOST_UDEV, h.USBHOST_POLKIT = udev, (pk,)
h.usbhost_ifaces = lambda: [{"name": "dhusb0", "usb": "0525:a4a2", "named": True, "ipv4": []}]
h.H.devices = {}


def nmcalls():
    try:
        return [x for x in open(NMLOG).read().split("\n")[:-1] if "general" not in x and "connection show" not in x]
    finally:
        open(NMLOG, "w").close()


st = h.usbhost_status()
expect("no root setup yet: blocked", (st["supported"], st["nm"], len(st["blockers"])), (True, True, 1))
try:
    h.usbhost_apply("share")
    expect("blocked apply refused", "ran", "refused")
except h.ApiError as e:
    expect("blocked apply refused, nothing changed", (e.code, nmcalls()), (409, []))
open(udev, "w").close(); open(pk, "w").close()
st = h.usbhost_status()
expect("set up: nothing blocks", (st["blockers"], st["profile"]), ([], None))
expect("share plan", [" ".join(c) for c in h.usbhost_plan("share", st)], [
    "nmcli connection add type ethernet con-name devicehub-usb connection.autoconnect yes connection.autoconnect-priority 50 "
    "match.interface-name dhusb* ipv6.method disabled ipv4.method shared ipv4.addresses 192.168.137.1/24",
    "nmcli connection up devicehub-usb ifname dhusb0"])
expect("remove with no profile: nothing", h.usbhost_plan("remove", st), [])
h.usbhost_apply("share")
expect("share applied", (len(nmcalls()), h.usbhost_status()["profile"]["mode"]), (2, "share"))
h.usbhost_apply("direct")
calls_ = nmcalls()
expect("direct: the profile is modified, not added again", (calls_[0].startswith("connection modify devicehub-usb"),
                                                             "ipv4.never-default yes" in calls_[0]), (True, True))
expect("direct applied", h.usbhost_status()["profile"]["addresses"], "192.168.7.1/24")
os.environ["NM_DENY"] = "1"
try:
    h.usbhost_apply("share")
    expect("polkit refusal reported", "ok", "error")
except h.ApiError as e:
    expect("polkit refusal points at the one-time setup", "install.sh --usb-host" in str(e), True)
del os.environ["NM_DENY"]
h.usbhost_apply("remove")
expect("removed", h.usbhost_status()["profile"], None)
try:
    h.usbhost_plan("everything")
    expect("unknown mode refused", "ok", "refused")
except h.ApiError:
    expect("unknown mode refused", "refused", "refused")
h.PLATFORM = "wsl"
expect("WSL: Windows owns the adapter", h.usbhost_status()["supported"], False)
expect("offline hint names Windows under WSL", "Windows" in h.usb_offline_msg(dict(h.DEVICE_DEFAULTS, host="192.168.7.2")), True)
h.PLATFORM = "linux"
expect("offline hint names Set up this PC on Linux", "Set up this PC" in h.usb_offline_msg(dict(h.DEVICE_DEFAULTS, host="192.168.7.2")), True)

print("PASS (%d checks)" % checks)
