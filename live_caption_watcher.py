#!/usr/bin/env python3
"""
Live Caption Watcher
====================
Silently watches Chrome's Live Caption bubble using accessibility APIs
(UI Automation on Windows, AT-SPI on Linux) and exits cleanly when a target
word or phrase appears in the transcribed text.

GOAL:
- Silently poll Chrome's Live Caption bubble.
- Print startup header once, then zero output until target word/phrase is detected.
- Print 'DETECTED: <target>' and exit with code 0 on match.

CLI Usage:
----------
  python live_caption_watcher.py [--word TARGET] [--phrase] [--case-sensitive] [--interval 0.2] [--verbose]

Arguments:
  --word, -w TARGET     Target word or phrase to watch for (optional; prompts interactively if omitted).
  --phrase              Match target as a phrase/substring rather than whole-word.
  --case-sensitive      Enable case-sensitive matching (default: case-insensitive).
  --interval SECONDS    Polling interval in seconds (default: 0.2).
  --verbose             Enable debug prints to stderr (default: silent).

Examples:
  python live_caption_watcher.py
  python live_caption_watcher.py --word "apple"
  python live_caption_watcher.py --word "apple pie" --phrase
  python live_caption_watcher.py -w "Secret" --case-sensitive --interval 0.1 --verbose

Platform Requirements & Dependencies:
--------------------------------------
1. Windows:
   Requires `uiautomation` package:
     pip install uiautomation

2. Linux:
   Requires AT-SPI Python bindings (`pyatspi`):
     sudo apt install python3-pyatspi
   Ensure accessibility is enabled in your desktop environment settings.

3. Chrome:
   Live Caption must already be enabled in Chrome:
     chrome://settings/accessibility -> Live Caption (On)
"""

import argparse
import platform
import re
import signal
import sys
import time
from collections import deque


def handle_sigint(signum, frame):
    """Clean exit on SIGINT (Ctrl-C) with exit code 0 and no traceback."""
    sys.exit(0)


signal.signal(signal.SIGINT, handle_sigint)


def get_current_caption_text_windows(verbose: bool = False) -> str:
    """
    Reads the current text from Chrome's Live Caption bubble on Windows
    using the UI Automation API (`uiautomation` module).
    """
    try:
        import uiautomation as auto

        root = auto.GetRootControl()

        # Strategy 1: Direct search for CaptionBubbleLabel control anywhere in tree
        lbl = root.Control(searchDepth=15, ClassName="CaptionBubbleLabel")
        if lbl.Exists(0, 0):
            text = lbl.Name or ""
            if text.strip():
                return text.strip()

            # Fallback to ValuePattern if Name is empty
            try:
                val_pattern = lbl.GetValuePattern()
                if val_pattern and val_pattern.Value:
                    return val_pattern.Value.strip()
            except Exception:
                pass

            # Fallback to children nodes if text is broken into spans
            children_text = []
            for child in lbl.GetChildren():
                if child.Name:
                    children_text.append(child.Name.strip())
            if children_text:
                return " ".join(children_text)

        # Strategy 2: Search for CaptionBubble container window
        bubble_win = root.Control(searchDepth=10, ClassName="CaptionBubble")
        if bubble_win.Exists(0, 0):
            # Inspect children inside CaptionBubble window
            for ctrl in bubble_win.GetChildren():
                if ctrl.Name and ctrl.Name.strip():
                    return ctrl.Name.strip()

        # Strategy 3: Iterate top-level Chrome windows for CaptionBubbleLabel
        top = root.GetFirstChildControl()
        while top:
            try:
                cname = top.ClassName or ""
                name = top.Name or ""
                if "Chrome" in cname or "Caption" in cname or "Live Caption" in name:
                    inner_lbl = top.Control(searchDepth=10, ClassName="CaptionBubbleLabel")
                    if inner_lbl.Exists(0, 0) and inner_lbl.Name and inner_lbl.Name.strip():
                        return inner_lbl.Name.strip()
            except Exception:
                pass
            top = top.GetNextSiblingControl()

    except ImportError:
        if verbose:
            print("[DEBUG] 'uiautomation' module not installed. Install with: pip install uiautomation", file=sys.stderr)
    except Exception as e:
        if verbose:
            print(f"[DEBUG] Error reading Windows UI Automation: {e}", file=sys.stderr)

    return ""


def get_current_caption_text_linux(verbose: bool = False) -> str:
    """
    Reads the current text from Chrome's Live Caption bubble on Linux
    using AT-SPI (`pyatspi` module).
    """
    try:
        import pyatspi

        registry = pyatspi.Registry
        desktop = registry.getDesktop(0)

        for app in desktop:
            if not app or not app.name:
                continue
            app_name = app.name.lower()
            if "chrome" in app_name or "chromium" in app_name:
                # Recursively inspect accessible elements for CaptionBubbleLabel or document role
                def find_caption_element(accessible, depth=0):
                    if depth > 10 or not accessible:
                        return None
                    try:
                        if accessible.name == "CaptionBubbleLabel":
                            return accessible
                        role_name = accessible.get_role_name()
                        if role_name in ("document frame", "label", "text"):
                            if "caption" in (accessible.name or "").lower():
                                return accessible
                        for child in accessible:
                            res = find_caption_element(child, depth + 1)
                            if res:
                                return res
                    except Exception:
                        pass
                    return None

                elem = find_caption_element(app)
                if elem:
                    try:
                        text_iface = elem.queryText()
                        text = text_iface.getText(0, -1)
                        if text and text.strip():
                            return text.strip()
                    except Exception:
                        pass
                    if elem.name and elem.name.strip():
                        return elem.name.strip()
    except ImportError:
        if verbose:
            print("[DEBUG] 'pyatspi' module not installed. Install via system package manager.", file=sys.stderr)
    except Exception as e:
        if verbose:
            print(f"[DEBUG] Error reading Linux AT-SPI: {e}", file=sys.stderr)

    return ""


def get_current_caption_text_stub(verbose: bool = False) -> str:
    """
    Fallback stub for unsupported platforms or custom backend extensions.
    """
    if verbose:
        print(f"[DEBUG] OS '{platform.system()}' is using the default caption text stub.", file=sys.stderr)
    return ""


def get_current_caption_text(verbose: bool = False) -> str:
    """
    Platform dispatch function to fetch the current Live Caption bubble text.
    Returns the caption string if found, otherwise empty string "".
    """
    system = platform.system()
    if system == "Windows":
        return get_current_caption_text_windows(verbose=verbose)
    elif system == "Linux":
        return get_current_caption_text_linux(verbose=verbose)
    else:
        return get_current_caption_text_stub(verbose=verbose)


def check_match(text: str, target: str, phrase: bool = False, case_sensitive: bool = False) -> bool:
    """
    Determines if `target` matches `text` based on phrase matching and case sensitivity rules.
    """
    if not text or not target:
        return False

    if not case_sensitive:
        text_cmp = text.lower()
        target_cmp = target.lower()
    else:
        text_cmp = text
        target_cmp = target

    if phrase:
        return target_cmp in text_cmp
    else:
        # Whole word match with regex word boundary
        pattern = r"\b" + re.escape(target_cmp) + r"\b"
        return bool(re.search(pattern, text_cmp))


def main():
    # Ensure stdout handles UTF-8 output cleanly on Windows console
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="Silently watch Chrome Live Caption bubble for a target word or phrase."
    )
    parser.add_argument("--word", "-w", type=str, help="Target word or phrase to watch for")
    parser.add_argument("positional_word", nargs="?", type=str, help="Target word or phrase (positional fallback)")
    parser.add_argument(
        "--phrase",
        action="store_true",
        help="Match target as a phrase/substring rather than whole-word (default: False)",
    )
    parser.add_argument(
        "--case-sensitive",
        action="store_true",
        help="Enable case-sensitive matching (default: case-insensitive)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.2,
        help="Polling interval in seconds (default: 0.2)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug prints to stderr (default: False)",
    )

    args = parser.parse_args()

    target = args.word or args.positional_word
    if not target:
        try:
            target = input("Enter the target word or phrase to watch for: ").strip()
            while not target:
                target = input("Enter the target word or phrase to watch for: ").strip()
        except (KeyboardInterrupt, EOFError):
            sys.exit(0)

    # Startup line (the ONLY output before match unless --verbose is enabled)
    print(f'Listening for "{target}" via Chrome Live Caption…')
    print("(Live Caption must already be enabled and media playing)")
    sys.stdout.flush()

    recent_texts = deque(maxlen=10)
    seen_snapshots = set()

    while True:
        try:
            caption_text = get_current_caption_text(verbose=args.verbose)

            if caption_text:
                if args.verbose:
                    print(f"[DEBUG] Current Live Caption text: {caption_text!r}", file=sys.stderr)

                # Check current text snapshot
                if check_match(caption_text, target, phrase=args.phrase, case_sensitive=args.case_sensitive):
                    print(f"DETECTED: {target}")
                    sys.stdout.flush()
                    sys.exit(0)

                # Check combined rolling buffer for streaming/partial updates
                if caption_text not in seen_snapshots:
                    seen_snapshots.add(caption_text)
                    recent_texts.append(caption_text)
                    combined_buffer_text = " ".join(recent_texts)
                    if check_match(combined_buffer_text, target, phrase=args.phrase, case_sensitive=args.case_sensitive):
                        print(f"DETECTED: {target}")
                        sys.stdout.flush()
                        sys.exit(0)

            time.sleep(args.interval)

        except KeyboardInterrupt:
            sys.exit(0)
        except Exception as e:
            if args.verbose:
                print(f"[DEBUG] Exception in polling loop: {e}", file=sys.stderr)
            time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
