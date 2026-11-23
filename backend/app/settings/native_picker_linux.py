from __future__ import annotations

import json
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk


def main() -> int:
    if not Gtk.init_check()[0]:
        print("No graphical desktop session is available", file=sys.stderr)
        return 1
    dialog = Gtk.FileChooserNative.new(
        "Choose folders", None, Gtk.FileChooserAction.SELECT_FOLDER, "Add", "Cancel"
    )
    dialog.set_select_multiple(True)
    if dialog.run() != Gtk.ResponseType.ACCEPT:
        print("[]")
        return 0
    paths = [item.get_path() for item in dialog.get_files()]
    if any(path is None for path in paths):
        print("Only mounted filesystem folders can be selected", file=sys.stderr)
        return 1
    print(json.dumps(paths, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
