"""
Translator Overlay — entry point.

Registers a global hotkey (Ctrl+Shift+T) that works even when the
application window is not focused.  Press the hotkey to trigger the
translation pipeline (currently prints to console).

Press Ctrl+C in the terminal to quit.
"""

import keyboard
import config


def on_hotkey_triggered() -> None:
    """Callback executed every time the global hotkey is pressed."""
    print("Hotkey triggered")


def main() -> None:
    print(f"Translator Overlay started.")
    print(f"Press  {config.HOTKEY.upper()}  to trigger translation.")
    print("Press  Ctrl+C  in the terminal to exit.\n")

    # Register the global hotkey — works system-wide, even without focus.
    keyboard.add_hotkey(config.HOTKEY, on_hotkey_triggered)

    # Block the main thread and keep the programme alive until Ctrl+C.
    try:
        keyboard.wait()          # waits forever
    except KeyboardInterrupt:
        print("\nShutting down…")
    finally:
        keyboard.unhook_all()


if __name__ == "__main__":
    main()
