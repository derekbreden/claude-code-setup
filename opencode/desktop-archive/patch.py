#!/usr/bin/env python3
"""Give OpenCode Desktop's session list an Archive item in its right-click menus.

usage: patch.py <original OpenCode.app> <patched OpenCode.app to write>

OpenCode Desktop 2.4.2 archives a session from the command palette ("Archive session",
Cmd+Shift+S) and from the Inbox layout's right-click menu, both through the service's
`session.update` with `archived`. The Side tabs layout's right-click menus have no Archive, and the Home
list's Archive button is stubbed out. This puts "Archive" first in the menu of an open tab
(archiving it closes the tab, as Cmd+Shift+S does) and of a recent session in the list, with
"Unarchive" in its place on an archived session (one opened from Search sessions), and makes the
Home list's button archive.

The app checks its bundled files: Info.plist carries the SHA-256 of app.asar's file index, and
the index carries each file's SHA-256. The changed script is appended to the end of app.asar,
its index entry is pointed at the new bytes with their hashes, the index hash in Info.plist is
updated, and the whole app is signed again ad hoc on this Mac (it no longer carries
OpenCode's own signature).

It refuses, changing nothing, when any anchor is not found exactly once: a new OpenCode version
has moved that code, and the anchors below need a fresh look.
"""
import hashlib
import json
import os
import plistlib
import struct
import subprocess
import sys

# Each edit is (anchor, replacement); every anchor must occur exactly once in one renderer script.
# The item is one component, defined beside the app's own "Mark as unread" item (zQ) and built the
# same way: `wz()` the translations, `tK().serverCtx(server)` the session's server context with its
# `sdk`, `$.Item` the menu item, `YG` the app's toast.
COMPONENT = ("function HSMarchiveItem(e){let t=wz(),n=tK(),r=()=>{let s=e.session,c=n.serverCtx(e.server);"
             "return s&&c?c.data.session.get(s.id)??s:s};return L($.Item,{get disabled(){let s=r();"
             "return!s||!!s.parentID},onSelect:()=>{let s=r(),c=n.serverCtx(e.server);if(!s||!c)return;"
             "let a=s.time.archived===void 0;c.sdk.api.session.update({sessionID:s.id,archived:a})"
             ".then(()=>{a&&e.onArchived?.()}).catch(x=>YG({title:t.t(`common.requestFailed`),"
             "description:String(x?.message??x)}))},get children(){let s=r();return t.t(s&&s.time.archived"
             "!==void 0?`sidebar.inbox.unarchive`:`common.archive`)}})}")
EDITS = [
    # the component, ahead of the app's "Mark as unread" item
    ("function zQ(e){let t=wz(),n=tK(),", COMPONENT + "function zQ(e){let t=wz(),n=tK(),"),
    # an open tab in the list: first in its menu; archiving closes the tab, as Cmd+Shift+S does
    ("L($.Item,{get disabled(){return!e.session},onSelect:()=>ue(`menu`),get children(){return t.t(`common.rename`)}})",
     "L(HSMarchiveItem,{get server(){return e.server},get session(){return e.session},get onArchived(){return e.onClose}}),"
     "L($.Item,{get disabled(){return!e.session},onSelect:()=>ue(`menu`),get children(){return t.t(`common.rename`)}})"),
    # a recent session in the list (not open as a tab): first in its menu
    ("L($.Item,{get disabled(){return!o()},onSelect:()=>r.show(()=>L(aCn,{get title(){return $Z(e.session)},"
     "onRename:t=>c(e.server,e.session,t)})),get children(){return t.t(`common.rename`)}})",
     "L(HSMarchiveItem,{get server(){return e.server},get session(){return e.session}}),"
     "L($.Item,{get disabled(){return!o()},onSelect:()=>r.show(()=>L(aCn,{get title(){return $Z(e.session)},"
     "onRename:t=>c(e.server,e.session,t)})),get children(){return t.t(`common.rename`)}})"),
    # the Home list's own Archive button, stubbed out in 2.4.2: the same service call
    ("archive:async e=>Promise.reject(Error(`Session archiving is unavailable`))",
     "archive:async e=>r.sdk.api.session.update({sessionID:e,archived:!0})"),
]
MARK = "HSMarchiveItem"
BLOCK = 4 * 1024 * 1024


def read_asar(path):
    with open(path, "rb") as fh:
        size_a, size_b, size_c, str_len = struct.unpack("<IIII", fh.read(16))
        raw = fh.read(str_len)
        base = 8 + size_b
        fh.seek(base)
        data = fh.read()
    return json.loads(raw), raw, data


def files(node, path=""):
    for name, child in node.get("files", {}).items():
        p = f"{path}/{name}"
        if "files" in child:
            yield from files(child, p)
        else:
            yield p, child


def main():
    src, dst = sys.argv[1], sys.argv[2]
    if os.path.exists(dst):
        sys.exit(f"{dst} exists: give a new path")
    header, raw, data = read_asar(os.path.join(src, "Contents/Resources/app.asar"))
    plist_path = os.path.join(src, "Contents/Info.plist")
    with open(plist_path, "rb") as fh:
        plist_bytes = fh.read()
    info = plistlib.loads(plist_bytes)
    recorded = info.get("ElectronAsarIntegrity", {}).get("Resources/app.asar", {}).get("hash")
    if recorded != hashlib.sha256(raw).hexdigest():
        sys.exit("Info.plist's app.asar hash does not match the file: not an untouched OpenCode.app")

    hits = []
    for path, entry in files(header):
        if not (path.startswith("/out/renderer/assets/") and path.endswith(".js")) or entry.get("unpacked"):
            continue
        offset, size = int(entry["offset"]), entry["size"]
        text = data[offset:offset + size]
        if MARK.encode() in text:
            sys.exit("already patched")
        if EDITS[0][0].encode() in text:
            hits.append((path, entry, text))
    if len(hits) != 1:
        sys.exit(f"the session menus' code was found in {len(hits)} scripts, not one: nothing changed")
    path, entry, text = hits[0]
    new_text = text
    for anchor, replacement in EDITS:
        count = new_text.count(anchor.encode())
        if count != 1:
            sys.exit(f"an anchor was found {count} times, not once: nothing changed\n  {anchor[:90]}")
        new_text = new_text.replace(anchor.encode(), replacement.encode(), 1)

    entry["offset"] = str(len(data))
    entry["size"] = len(new_text)
    entry["integrity"] = {
        "algorithm": "SHA256",
        "hash": hashlib.sha256(new_text).hexdigest(),
        "blockSize": BLOCK,
        "blocks": [hashlib.sha256(new_text[i:i + BLOCK]).hexdigest() for i in range(0, len(new_text), BLOCK)],
    }
    new_raw = json.dumps(header, separators=(",", ":")).encode()
    aligned = (len(new_raw) + 3) & ~3
    size_c = 4 + aligned
    size_b = 4 + size_c

    subprocess.run(["cp", "-Rc", src, dst], check=True)
    asar = os.path.join(dst, "Contents/Resources/app.asar")
    tmp = asar + ".new"
    with open(tmp, "wb") as fh:
        fh.write(struct.pack("<IIII", 4, size_b, size_c, len(new_raw)))
        fh.write(new_raw + b"\0" * (aligned - len(new_raw)))
        fh.write(data)
        fh.write(new_text)
    os.replace(tmp, asar)

    info["ElectronAsarIntegrity"]["Resources/app.asar"]["hash"] = hashlib.sha256(new_raw).hexdigest()
    fmt = plistlib.FMT_BINARY if plist_bytes.startswith(b"bplist") else plistlib.FMT_XML
    with open(os.path.join(dst, "Contents/Info.plist"), "wb") as fh:
        plistlib.dump(info, fh, fmt=fmt)

    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", dst], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", dst], check=True)
    print(f"patched {path} ({len(text)} -> {len(new_text)} bytes); index hash {hashlib.sha256(new_raw).hexdigest()}; signed ad hoc: {dst}")


if __name__ == "__main__":
    main()
