#!/usr/bin/env python3
# Save an XWayland window's own icon as a PNG and print its path.
#
#   window-icon.py <pid> <title>
#
# Wine and Proton windows share a generic class (steam_app_default) with no
# desktop entry, but Wine sets _NET_WM_ICON on each window from the program's
# executable. Icons are cached per executable, so later launches skip xprop.
# Prints nothing when the window has no icon.

import hashlib
import os
import re
import struct
import subprocess
import sys
import zlib


def xprop(*args):
    result = subprocess.run(["xprop", *args], capture_output=True, text=True, timeout=2)
    return result.stdout if result.returncode == 0 else ""


def property_value(output, name):
    # xprop prints "NAME(TYPE) = value", "NAME = value", or for window lists
    # "NAME(WINDOW): window id # value".
    for line in output.splitlines():
        match = re.match(r"(\w+)(?:\([^)]*\))?\s*[=:]\s*(.*)", line)
        if match and match.group(1) == name:
            return match.group(2).strip()
    return None


def find_window(pid, title):
    clients = property_value(xprop("-root", "_NET_CLIENT_LIST"), "_NET_CLIENT_LIST") or ""
    candidates = []
    for window_id in clients.replace("window id #", "").split(","):
        window_id = window_id.strip()
        if not window_id:
            continue
        output = xprop("-id", window_id, "_NET_WM_PID", "_NET_WM_NAME", "WM_NAME")
        if property_value(output, "_NET_WM_PID") != str(pid):
            continue
        names = {property_value(output, "_NET_WM_NAME"), property_value(output, "WM_NAME")}
        if '"%s"' % title in names:
            return window_id
        candidates.append(window_id)
    return candidates[0] if candidates else None


def largest_icon(window_id):
    output = xprop("-id", window_id, "-notype", "32c", "_NET_WM_ICON")
    value = property_value(output, "_NET_WM_ICON")
    if not value:
        return None

    try:
        data = [int(item) for item in value.split(",")]
    except ValueError:
        return None

    # The property holds one or more images: width, height, then width*height
    # ARGB pixels each.
    best = None
    offset = 0
    while offset + 2 <= len(data):
        width, height = data[offset], data[offset + 1]
        end = offset + 2 + width * height
        if width <= 0 or height <= 0 or end > len(data):
            break
        if best is None or width * height > best[0] * best[1]:
            best = (width, height, data[offset + 2:end])
        offset = end
    return best


def write_png(path, width, height, pixels):
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for argb in pixels[y * width:(y + 1) * width]:
            rows += bytes(((argb >> 16) & 255, (argb >> 8) & 255, argb & 255, (argb >> 24) & 255))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(rows)))
    png += chunk(b"IEND", b"")

    temporary = path + ".tmp"
    with open(temporary, "wb") as file:
        file.write(png)
    os.replace(temporary, path)


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: window-icon.py <pid> <title>")
    pid, title = sys.argv[1], sys.argv[2]

    # Wine reports the Windows path of the program as argv[0], which is stable
    # across launches where the pid and often the title are not.
    try:
        with open("/proc/%s/cmdline" % pid, "rb") as file:
            program = file.read().split(b"\0")[0]
    except OSError:
        return

    cache = os.path.join(
        os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
        "omarchy",
        "io.github.pablo-merino.altswitch",
        "icons",
    )
    path = os.path.join(cache, hashlib.sha1(program).hexdigest()[:16] + ".png")

    if not os.path.exists(path):
        window_id = find_window(pid, title)
        icon = largest_icon(window_id) if window_id else None
        if not icon:
            return
        os.makedirs(cache, exist_ok=True)
        write_png(path, *icon)

    print(path)


if __name__ == "__main__":
    main()
