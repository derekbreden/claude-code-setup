# Archive in OpenCode Desktop's session list

OpenCode Desktop 2.4.2 can archive a session: "Archive session" in the command palette
(Cmd+Shift+S) archives the open session and closes its tab, and pressing it again on an
archived session restores it. Search sessions still finds archived sessions. The Inbox
layout's right-click menu has Archive too. The Side tabs layout's right-click menu has none,
and the Home list's Archive is stubbed out ("Session archiving is unavailable").

`patch.py` puts Archive first in both right-click menus the Side tabs list has: the menu of an
open tab (archiving it closes the tab, as Cmd+Shift+S does) and the menu of a recent session
that is not open. On an archived session, one opened from Search sessions, the item reads
Unarchive. It also makes the Home list's Archive button work. All of them go through the
service's `session.update` with `archived`, the call the command palette uses.

## Apply

Quit OpenCode first. On 27 November its background service (`opencode-cli serve --service`)
kept running after the app quit, and the relaunched app picked it up again.

```sh
python3 -I opencode/desktop-archive/patch.py /Applications/OpenCode.app /tmp/OpenCode-patched.app
```

Then put the original aside and the patched copy in its place:

```sh
mkdir -p ~/Library/Application\ Support/opencode-desktop-archive
mv /Applications/OpenCode.app ~/Library/Application\ Support/opencode-desktop-archive/OpenCode-<version>.app.original
mv /tmp/OpenCode-patched.app /Applications/OpenCode.app
```

Open OpenCode from the Dock. The `.original` suffix keeps the saved copy from being found as an app.

## What it changes

- `Contents/Resources/app.asar`: the renderer script holding the session menus gets the item
  (one component, beside the app's own "Mark as unread" item) and the Home button's call,
  appended as new bytes, with its index entry pointing at them and carrying their SHA-256.
- `Contents/Info.plist`: `ElectronAsarIntegrity`, the SHA-256 of app.asar's index, which the
  app checks at launch.
- The app is signed again, ad hoc, on this Mac. It no longer carries OpenCode's own signature,
  so macOS may ask once for the login password to let OpenCode read its keychain item.

## After an OpenCode update

An update replaces the app and the item is gone. The updater may also refuse to update an app
signed this way: if it does, put the `.original` copy back first, update, then patch again.
`patch.py` refuses, changing nothing, when the menu's code is not found exactly once, because
a new version moved it. If a version's own Side tabs menu has Archive, drop the patch.

## Restore

Quit OpenCode, then:

```sh
rm -rf /Applications/OpenCode.app
mv ~/Library/Application\ Support/opencode-desktop-archive/OpenCode-<version>.app.original /Applications/OpenCode.app
```
