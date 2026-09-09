#!/usr/bin/env python3
"""
live_caption_watcher.py
=======================
Silently watches Chrome's Live Caption window using Windows UI Automation
and exits cleanly when a target word or phrase appears in the transcribed text.

GOAL:
- Silently poll Chrome's Live Caption window.
- Print startup header once, then zero output until target is detected.
- Print 'DETECTED: <target>' and exit with code 0 on match.

CLI Usage:
----------
python live_caption_watcher.py [--word TARGET] [--phrase] [--case-sensitive]
                               [--interval 0.2] [--verbose]

Arguments:
  --word, -w TARGET     Target word or phrase to watch for
                        (optional; prompts interactively if omitted).
  --phrase              Match the entire phrase rather than whole-word.
  --case-sensitive      Enable case-sensitive matching (default: case-insensitive).
  --interval SECONDS    Polling interval in seconds (default: 0.25).
  --verbose             Enable debug prints to stderr (default: silent).

Examples:
  python live_caption_watcher.py
  python live_caption_watcher.py --word "apple"
  python live_caption_watcher.py --word "apple pie" --phrase
  python live_caption_watcher.py -w "Secret" --case-sensitive --interval 0.1 --verbose
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Optional

try:
    import uiautomation as auto
except ImportError:
    print("Missing dependency. Install with:\n  pip install uiautomation comtypes", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Live Caption window finder + text extractor
# ---------------------------------------------------------------------------

def get_live_caption_text() -> Optional[str]:
    """
    Find Chrome's Live Caption top-level window and return its current text.
    Returns None if the window is not found or text cannot be read.
    """
    # Primary search – most common Chrome Live Caption window
    win = auto.WindowControl(
        searchDepth=1,
        ClassName="Chrome_WidgetWin_1",
        SubName="Live Caption",          # partial match is intentional
    )

    if not win.Exists(0.4):
        # Fallback 1 – pure Name match
        win = auto.WindowControl(searchDepth=1, Name="Live Caption")
        if not win.Exists(0.3):
            # Fallback 2 – any Chrome window that mentions "Caption"
            for child in auto.GetRootControl().GetChildren():
                name = (child.Name or "").lower()
                cls = (child.ClassName or "")
                if "chrome" in cls.lower() and "caption" in name:
                    win = child
                    break
            else:
                return None

    # Try to extract the actual caption text
    # Method A: DocumentControl (works on many Chrome versions)
    try:
        doc = win.DocumentControl(searchDepth=6)
        if doc.Exists(0.15):
            text = (doc.Name or "").strip()
            if text:
                return text
    except Exception:
        pass

    # Method B: any TextControl deeper in the tree
    try:
        text_ctrl = win.TextControl(searchDepth=10)
        if text_ctrl.Exists(0.15):
            text = (text_ctrl.Name or "").strip()
            if text:
                return text
    except Exception:
        pass

    # Method C: walk a few levels looking for the longest Name
    try:
        best = ""
        for ctrl in win.GetChildren():
            for sub in ctrl.GetChildren():
                name = (sub.Name or "").strip()
                if len(name) > len(best):
                    best = name
        if best:
            return best
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------

def matches(text: str, target: str, *, phrase: bool, case_sensitive: bool) -> bool:
    if not text or not target:
        return False

    if not case_sensitive:
        text = text.lower()
        target = target.lower()

    if phrase:
        return target in text

    # Whole-word style match (simple but effective)
    # Treats punctuation as word boundaries
    import re
    pattern = r"(?<!\w)" + re.escape(target) + r"(?!\w)"
    return bool(re.search(pattern, text))


# ---------------------------------------------------------------------------
# Main watcher loop
# ---------------------------------------------------------------------------

def watch(
    target: str,
    *,
    phrase: bool = False,
    case_sensitive: bool = False,
    interval: float = 0.25,
    verbose: bool = False,
) -> None:
    print(f'Listening for "{target}" via Chrome Live Caption...')
    print("(Live Caption must already be enabled and media playing)\n")

    last_text = ""
    poll_count = 0

    while True:
        poll_count += 1
        text = get_live_caption_text()

        if text is None:
            if verbose and poll_count % 20 == 0:
                print("[verbose] Live Caption window not found yet...", file=sys.stderr)
        elif text != last_text:
            last_text = text
            if verbose:
                print(f"[caption] {text}", file=sys.stderr)

            if matches(text, target, phrase=phrase, case_sensitive=case_sensitive):
                print(f"DETECTED: {target}")
                sys.exit(0)

        time.sleep(interval)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Silently watch Chrome Live Caption and exit when a target word/phrase appears.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("-w", "--word", dest="target", help="Target word or phrase")
    parser.add_argument("--phrase", action="store_true", help="Match as substring/phrase instead of whole word")
    parser.add_argument("--case-sensitive", action="store_true", help="Case-sensitive matching")
    parser.add_argument("--interval", type=float, default=0.25, help="Polling interval in seconds (default: 0.25)")
    parser.add_argument("--verbose", action="store_true", help="Print debug info to stderr")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    target = args.target
    if not target:
        try:
            target = input("Enter the target word or phrase to watch for: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            sys.exit(1)

    if not target:
        print("No target provided. Exiting.", file=sys.stderr)
        sys.exit(1)

    try:
        watch(
            target,
            phrase=args.phrase,
            case_sensitive=args.case_sensitive,
            interval=max(0.05, args.interval),
            verbose=args.verbose,
        )
    except KeyboardInterrupt:
        print("\nStopped by user.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()