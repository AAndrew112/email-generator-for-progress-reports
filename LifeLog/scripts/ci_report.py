"""Summarises a UI-test result bundle for CI.

  python3 ci_report.py failures <path.xcresult>       → ::error annotations per failing test
  python3 ci_report.py images <attachments-dir> START COUNT
                                                       → small JPEG screenshots as ::notice annotations
"""
import base64
import json
import os
import subprocess
import sys


def escape(text):
    return text.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


def failures(bundle):
    out = subprocess.run(["xcrun", "xcresulttool", "get", "test-results", "tests", "--path", bundle],
                         capture_output=True, text=True).stdout
    try:
        data = json.loads(out)
    except ValueError:
        print(out[:4000])
        return
    found = []

    def walk(node, test=None):
        kind = node.get("nodeType")
        if kind == "Test Case":
            test = node.get("name")
            print(f"{node.get('result')}: {test}")
        if kind == "Failure Message":
            found.append((test, node.get("name", "")))
        for child in node.get("children", []):
            walk(child, test)

    for node in data.get("testNodes", []):
        walk(node)
    for test, message in found[:10]:
        print(f"::error title=UITest {escape(test or '')}::{escape(message)}")
        print(f"FAIL {test}: {message}")


def images(directory, start, count):
    manifest = json.load(open(os.path.join(directory, "manifest.json")))
    shots = []
    for test in manifest:
        for att in test.get("attachments", []):
            name = att.get("exportedFileName", "")
            if name.lower().endswith((".png", ".jpg", ".jpeg", ".heic")):
                label = att.get("suggestedHumanReadableName", name)
                shots.append((f"{test.get('testIdentifier', '')} {label}", os.path.join(directory, name)))
    print(f"{len(shots)} screenshots")
    for i, (label, path) in enumerate(shots[start:start + count]):
        subprocess.run(["sips", "-Z", "430", "-s", "format", "jpeg", "-s", "formatOptions", "45", path,
                        "--out", "/tmp/shot.jpg"], capture_output=True)
        data = base64.b64encode(open("/tmp/shot.jpg", "rb").read()).decode()
        print(f"::notice title=IMG {start + i:02d} {escape(label)[:120]}::{data}")


def crashes():
    """Prints the crashed thread of recent LifeLog crash reports (simulator writes them to the host)."""
    import glob
    reports = sorted(glob.glob(os.path.expanduser("~/Library/Logs/DiagnosticReports/LifeLog*.ips")), key=os.path.getmtime)
    print(f"{len(reports)} crash reports")
    for path in reports[-2:]:
        text = open(path, errors="replace").read()
        header, _, body = text.partition("\n")
        try:
            report = json.loads(body)
        except ValueError:
            print(text[:3000])
            continue
        lines = [f"exception: {json.dumps(report.get('exception'))}",
                 f"termination: {json.dumps(report.get('termination'))}",
                 f"asi: {json.dumps(report.get('asi'))}"]
        images = report.get("usedImages", [])
        for t in report.get("threads", []):
            if not t.get("triggered"):
                continue
            for f in t.get("frames", [])[:30]:
                image = images[f.get("imageIndex", 0)].get("name", "?") if images else "?"
                lines.append(f"  {image} {f.get('symbol', '?')} +{f.get('symbolLocation', 0)} {f.get('sourceFile', '')}:{f.get('sourceLine', '')}")
        msg = "\n".join(lines)
        print(msg)
        print(f"::error title=Crash {escape(os.path.basename(path))}::{escape(msg)[:60000]}")


if __name__ == "__main__":
    if sys.argv[1] == "crashes":
        crashes()
    elif sys.argv[1] == "failures":
        failures(sys.argv[2])
    else:
        images(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))
