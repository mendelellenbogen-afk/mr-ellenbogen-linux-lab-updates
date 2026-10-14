"""Shared TDSB-WIFI helpers for the school account system (runs as root).

Students (9-digit IDs) and staff (6-digit IDs) log in with their TDSB ID: 3-27
letters or digits. The laptop account is named "tdsb-" + the ID in lowercase
(e.g. tdsb-123456789, tdsb-123456). The prefix keeps TDSB accounts from ever
clashing with local accounts like "administrator". The ID exactly as typed is
stored as the account's full name: the login screen shows it, and it is the
identity sent to TDSB-WIFI.

TDSB-WIFI settings (from the school's own instructions):
  WPA/WPA2 Enterprise, PEAP, inner auth MSCHAPv2, no CA certificate,
  identity = student ID, password = student password.

Connections are created IN MEMORY only (never written to disk) through
NetworkManager's D-Bus API, so passwords never appear on a command line or in
a file, and they vanish at reboot. school-forget-wifi removes them at logout.
"""

import re
import subprocess
import time
import uuid

import dbus

SSID = "TDSB-WIFI"
LOGIN_ID_PATTERN = re.compile(r"^[A-Za-z0-9]{3,27}$")
ACCOUNT_PATTERN = re.compile(r"^tdsb-[a-z0-9]{3,27}$")
ACCOUNT_PREFIX = "tdsb-"

VERIFY_CONNECTION_ID = "TDSB-WIFI (account check)"
ACTIVATION_TIMEOUT_SECONDS = 45

NM_BUS = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"
NM_SETTINGS_PATH = "/org/freedesktop/NetworkManager/Settings"
PROPS = "org.freedesktop.DBus.Properties"

ADD_FLAG_IN_MEMORY = 0x2
ADD_FLAG_BLOCK_AUTOCONNECT = 0x20
DEVICE_TYPE_WIFI = 2
ACTIVE_STATE_ACTIVATED = 2


class WifiError(Exception):
    """A problem a student should see as a short, plain message."""


def is_login_id(text):
    return bool(LOGIN_ID_PATTERN.fullmatch(text or ""))


def username_for(login_id):
    return ACCOUNT_PREFIX + login_id.lower()


def is_tdsb_account(username):
    return bool(ACCOUNT_PATTERN.fullmatch(username or ""))


def login_id_for(username, full_name=""):
    """The TDSB ID for a laptop account: its full name if that matches, else the name part."""
    if not is_tdsb_account(username):
        return None
    candidate = (full_name or "").split(",")[0].strip()
    if is_login_id(candidate) and username_for(candidate) == username:
        return candidate
    return username[len(ACCOUNT_PREFIX):]


def connection_name_for(username):
    return f"TDSB-WIFI ({username})"


def connection_settings(connection_id, student_id, password, autoconnect, owner=None):
    connection = {
        "id": connection_id,
        "uuid": str(uuid.uuid4()),
        "type": "802-11-wireless",
        "autoconnect": dbus.Boolean(autoconnect),
    }

    if owner:
        connection["permissions"] = dbus.Array([f"user:{owner}:"], signature="s")

    return dbus.Dictionary({
        "connection": dbus.Dictionary(connection, signature="sv"),
        "802-11-wireless": dbus.Dictionary({
            "ssid": dbus.ByteArray(SSID.encode()),
            "mode": "infrastructure",
        }, signature="sv"),
        "802-11-wireless-security": dbus.Dictionary({
            "key-mgmt": "wpa-eap",
        }, signature="sv"),
        "802-1x": dbus.Dictionary({
            "eap": dbus.Array(["peap"], signature="s"),
            "identity": student_id,
            "password": password,
            "phase2-auth": "mschapv2",
            "system-ca-certs": dbus.Boolean(False),
        }, signature="sv"),
        "ipv4": dbus.Dictionary({"method": "auto"}, signature="sv"),
        "ipv6": dbus.Dictionary({"method": "auto"}, signature="sv"),
    }, signature="sa{sv}")


def _bus():
    return dbus.SystemBus()


def _nm(bus):
    return dbus.Interface(bus.get_object(NM_BUS, NM_PATH), NM_BUS)


def _settings(bus):
    return dbus.Interface(
        bus.get_object(NM_BUS, NM_SETTINGS_PATH), NM_BUS + ".Settings"
    )


def _wifi_device(bus):
    for path in _nm(bus).GetDevices():
        props = dbus.Interface(bus.get_object(NM_BUS, path), PROPS)
        if props.Get(NM_BUS + ".Device", "DeviceType") == DEVICE_TYPE_WIFI:
            return path
    raise WifiError("This laptop's Wi-Fi was not found.")


def _connections_named(name):
    bus = _bus()
    found = []
    for path in _settings(bus).ListConnections():
        connection = dbus.Interface(
            bus.get_object(NM_BUS, path), NM_BUS + ".Settings.Connection"
        )
        try:
            if connection.GetSettings()["connection"]["id"] == name:
                found.append(connection)
        except dbus.DBusException:
            pass
    return found


def connection_exists(name):
    return bool(_connections_named(name))


def delete_connections_named(name):
    """Remove every saved/in-memory connection with this name (no error if none)."""
    for connection in _connections_named(name):
        try:
            connection.Delete()
        except dbus.DBusException:
            pass


def tdsb_wifi_in_range():
    subprocess.run(["/usr/bin/nmcli", "radio", "wifi", "on"], capture_output=True, check=False)
    result = subprocess.run(
        ["/usr/bin/nmcli", "-t", "-f", "SSID", "device", "wifi", "list", "--rescan", "yes"],
        capture_output=True, text=True, check=False, timeout=30,
    )
    return SSID in result.stdout.splitlines()


def check_credentials(student_id, password):
    """Return True if TDSB-WIFI accepts this student ID and password.

    Raises WifiError when the check can't be done (e.g. TDSB-WIFI not in range).
    """
    if not is_login_id(student_id):
        raise WifiError("Your ID is 3 to 27 letters or numbers.")

    if not password:
        raise WifiError("Please enter your password.")

    if not tdsb_wifi_in_range():
        raise WifiError("TDSB-WIFI was not found. Accounts can only be created at school.")

    bus = _bus()
    device = _wifi_device(bus)
    delete_connections_named(VERIFY_CONNECTION_ID)

    connection_path, _ = _settings(bus).AddConnection2(
        connection_settings(VERIFY_CONNECTION_ID, student_id, password, autoconnect=False),
        dbus.UInt32(ADD_FLAG_IN_MEMORY | ADD_FLAG_BLOCK_AUTOCONNECT),
        dbus.Dictionary({}, signature="sv"),
    )

    try:
        active_path = _nm(bus).ActivateConnection(connection_path, device, "/")
        deadline = time.monotonic() + ACTIVATION_TIMEOUT_SECONDS

        while time.monotonic() < deadline:
            try:
                props = dbus.Interface(bus.get_object(NM_BUS, active_path), PROPS)
                state = props.Get(NM_BUS + ".Connection.Active", "State")
            except dbus.DBusException:
                return False        # NetworkManager gave up: credentials rejected

            if state == ACTIVE_STATE_ACTIVATED:
                return True

            if state == 4:          # deactivated
                return False

            time.sleep(0.5)

        return False

    finally:
        delete_connections_named(VERIFY_CONNECTION_ID)


def add_session_connection(username, password):
    """Give a logged-in student/staff member a TDSB-WIFI connection with their own credentials.

    In memory only, usable only by that student, and it connects automatically
    whenever TDSB-WIFI is in range. Removed at logout by school-forget-wifi.
    """
    import pwd
    try:
        full_name = pwd.getpwnam(username).pw_gecos
    except KeyError:
        return
    student_id = login_id_for(username, full_name)
    if not student_id or not password:
        return

    name = connection_name_for(username)

    # Unlocking the screen also runs this. Keep an existing connection rather
    # than dropping the student's Wi-Fi on every unlock.
    if connection_exists(name):
        return

    _settings(_bus()).AddConnection2(
        connection_settings(name, student_id, password, autoconnect=True, owner=username),
        dbus.UInt32(ADD_FLAG_IN_MEMORY),
        dbus.Dictionary({}, signature="sv"),
    )
