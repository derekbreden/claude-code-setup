#!/usr/bin/env python3
"""Give OpenCode Desktop's session list an Archive item in its right-click menu.

usage: patch.py <original OpenCode.app> <patched OpenCode.app to write>

OpenCode Desktop 2.4.2 archives a session from the command palette ("Archive session",
Cmd+Shift+S) and from the Inbox layout's right-click menu, both through the service's
`session.update` with `archived`. The Side tabs layout's right-click menu has no Archive. This
adds one at the top of that menu: "Archive" on a session that is not archived (it archives it
and closes its tab, as Cmd+Shift+S does), "Unarchive" on one that is (one opened from Search
sessions).

The app checks its bundled files: Info.plist carries the SHA-256 of app.asar's file index, and
the index carries each file's SHA-256. The changed script is appended to the end of app.asar,
its index entry is pointed at the new bytes with their hashes, the index hash in Info.plist is
updated, and the whole app is signed again ad hoc on this Mac (it no longer carries
OpenCode's own signature).

It refuses, changing nothing, when the menu's code is not found exactly once: a new OpenCode
version has moved it, and the anchor below needs a fresh look.
"""
import hashlib
import json
import os
import plistlib
import struct
import subprocess
import sys

ANCHOR = ("L($.Item,{get disabled(){return!e.session},onSelect:()=>ue(`menu`),"
          "get children(){return t.t(`common.rename`)}})")
# Inside the session tab component: `e` is the tab's props (session, server, onClose), `h()` the
# session's server context (its `sdk`), `t` the translations, `YG` the app's toast.
ITEM = ("L($.Item,{get disabled(){return!e.session||!!e.session.parentID},onSelect:()=>{"
        "let __s=e.session,__c=h();if(!__s||!__c)return;let __a=__s.time.archived===void 0;"
        "__c.sdk.api.session.update({sessionID:__s.id,archived:__a})"
        ".then(()=>{__a&&e.onClose?.()})"
        ".catch(__e=>YG({title:t.t(`common.requestFailed`),description:String(__e?.message??__e)}))},"
        "get children(){return t.t(e.session?.time.archived!==void 0?`sidebar.inbox.unarchive`:`common.archive`)}}),")
MARK = "__a&&e.onClose?.()"
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
        if ANCHOR.encode() in text:
            hits.append((path, entry, text))
    if len(hits) != 1 or hits[0][2].count(ANCHOR.encode()) != 1:
        sys.exit(f"the session menu's code was found {sum(h[2].count(ANCHOR.encode()) for h in hits)} times, not once: nothing changed")
    path, entry, text = hits[0]
    if MARK.encode() in text:
        sys.exit("already patched")
    new_text = text.replace(ANCHOR.encode(), (ITEM + ANCHOR).encode(), 1)

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
