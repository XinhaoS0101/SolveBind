from __future__ import annotations

import subprocess


def tap(adb_path, x, y):
    command = adb_path + f" shell input tap {x} {y}"
    subprocess.run(command, capture_output=True, text=True, shell=True)


def swipe(adb_path, x1, y1, x2, y2, duration_ms=600):
    command = adb_path + f" shell input swipe {x1} {y1} {x2} {y2} {duration_ms}"
    result = subprocess.run(command, capture_output=True, text=True, shell=True)
    return result.returncode == 0


def type_text(adb_path, text):
    text = text.replace("\\n", "_").replace("\n", "_")
    for char in text:
        if char == " ":
            command = adb_path + " shell input text %s"
        elif char == "_":
            command = adb_path + " shell input keyevent 66"
        elif "a" <= char <= "z" or "A" <= char <= "Z" or char.isdigit():
            command = adb_path + f" shell input text {char}"
        elif char in "-.,!?@'°/:;()":
            command = adb_path + f" shell input text \"{char}\""
        else:
            command = adb_path + f" shell am broadcast -a ADB_INPUT_TEXT --es msg \"{char}\""
        subprocess.run(command, capture_output=True, text=True, shell=True)


def ime_shown(adb_path):
    result = subprocess.run(
        adb_path + " shell dumpsys input_method",
        capture_output=True,
        text=True,
        shell=True,
    )
    out = result.stdout or ""
    return any(key in out for key in ("mInputShown=true", "mIsInputViewShown=true"))


def back(adb_path):
    command = adb_path + " shell input keyevent 4"
    subprocess.run(command, capture_output=True, text=True, shell=True)
