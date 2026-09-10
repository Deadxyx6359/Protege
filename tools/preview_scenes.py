"""Render scene studies without loading models, user settings, or conversations.

    python tools/preview_scenes.py --out-dir artifacts/scenes
    python tools/preview_scenes.py --case space --frames --out-dir artifacts/scenes
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from PySide6.QtCore import QDateTime, QEventLoop, QTimer
from PySide6.QtGui import QGuiApplication
from protege.ui.engine import build_engine, configure_application, load

CASES = {
    "summer": ("coast", "2026-07-15T14:00:00", "clear"),
    "spring": ("coast", "2026-04-15T10:00:00", "clear"),
    "autumn": ("coast", "2026-10-20T17:30:00", "clear"),
    "halloween": ("coast", "2026-10-31T21:00:00", "fog"),
    "winter": ("coast", "2026-12-25T16:30:00", "snow"),
    "dawn": ("coast", "2026-07-15T06:00:00", "clear"),
    "night": ("coast", "2026-07-15T23:00:00", "clear"),
    "drizzle": ("coast", "2026-07-15T14:00:00", "drizzle"),
    "storm": ("coast", "2026-07-15T14:00:00", "thunder"),
    "blizzard": ("coast", "2026-12-25T14:00:00", "blizzard"),
    "space": ("space", "2026-07-15T14:00:00", "clear"),
}


def write_gallery(directory: Path, captures: list[dict]) -> None:
    """A portable, offline review page; its images are embedded, not fetched."""
    grouped = {}
    for capture in captures:
        name = capture["case"]
        grouped.setdefault(name, []).append(
            "data:image/png;base64," + base64.b64encode(Path(capture["path"]).read_bytes()).decode("ascii")
        )
    data = json.dumps(grouped)
    page = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Protégé · Two quiet worlds</title>
<style>
:root{color-scheme:dark;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#0c121b;color:#e3e9e8}
body{max-width:1280px;margin:auto;padding:32px 28px}header{display:flex;align-items:end;justify-content:space-between;gap:24px;margin-bottom:24px}
small{color:#93a6ab;font-size:11px;letter-spacing:.18em;text-transform:uppercase}h1{font-size:32px;letter-spacing:-.04em;font-weight:500;margin:10px 0 0}
button{font:inherit;background:#1b2833;border:1px solid #34444c;border-radius:20px;padding:9px 16px;color:inherit;cursor:pointer}
button[aria-pressed=true]{background:#d2e2dc;color:#15242b;border-color:#d2e2dc}button:focus-visible{outline:2px solid #e7c59c;outline-offset:3px}
nav{display:flex;gap:7px;flex-wrap:wrap;margin:20px 0}figure{margin:0;overflow:hidden;border:1px solid #293c48;border-radius:18px;background:#09101c}
img{display:block;width:100%;height:auto;image-rendering:pixelated;aspect-ratio:16/9}footer{display:flex;justify-content:space-between;color:#93a6ab;font-size:12px;margin-top:16px;gap:24px}
@media(max-width:650px){body{padding:20px 14px}h1{font-size:25px}footer{display:block;line-height:1.8}}
</style>
<header><div><small>Protégé / scene studies</small><h1>Two quiet worlds.</h1></div><button id="play">Pause animation</button></header>
<nav aria-label="Choose a scene" id="scenes"></nav>
<figure><img id="painting" alt=""></figure>
<footer><span id="caption"></span><span>Illustrated conditions · Preview uses fixed dates, not live weather</span></footer>
<script>
const images=DATA;
const names={summer:'Summer bay',spring:'Spring blossoms',autumn:'Autumn evening',halloween:'All Hallows’ Eve',winter:'Winter cottage',dawn:'First light',night:'Moonlit bay',drizzle:'Passing drizzle',storm:'Storm front',blizzard:'Snow squall',space:'The far station'};
let chosen=Object.keys(images)[0], frame=0, playing=!matchMedia('(prefers-reduced-motion: reduce)').matches,timer;
const painting=document.getElementById('painting'),play=document.getElementById('play');
function draw(){painting.src=images[chosen][frame];painting.alt=names[chosen];document.getElementById('caption').textContent=names[chosen];}
function tick(){clearTimeout(timer);play.textContent=playing?'Pause animation':'Play animation';draw();if(playing){timer=setTimeout(()=>{frame=(frame+1)%images[chosen].length;tick()},chosen==='space'?1400:['storm','blizzard','winter'].includes(chosen)?300:1100)}}
for(const name of Object.keys(images)){const button=document.createElement('button');button.textContent=names[name];button.setAttribute('aria-pressed',name===chosen);button.onclick=()=>{chosen=name;frame=0;document.querySelectorAll('nav button').forEach(b=>b.setAttribute('aria-pressed',b===button));tick()};document.getElementById('scenes').append(button)}
play.onclick=()=>{playing=!playing;tick()};document.addEventListener('visibilitychange',()=>{if(document.hidden)clearTimeout(timer);else tick()});tick();
</script></html>""".replace("DATA", data)
    (directory / "gallery.html").write_text(page, encoding="utf-8")


def settle(window, ms=220):
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(16)
    timer.timeout.connect(window.requestUpdate)
    timer.start()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    timer.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=list(CASES), action="append")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--frames", action="store_true")
    parser.add_argument("--size", default="1440x810")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication(sys.argv[:1])
    configure_application(app)
    engine, theme = build_engine()
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
    window = load(engine, REPO / "protege/ui/qml/SceneGallery.qml")
    w, h = map(int, args.size.split("x"))
    window.setWidth(w)
    window.setHeight(h)
    captures = []
    for name in args.case or CASES:
        scene, date, weather = CASES[name]
        start = time.perf_counter()
        window.setProperty("sceneName", scene)
        window.setProperty("sceneDate", QDateTime.fromString(date, "yyyy-MM-ddTHH:mm:ss"))
        window.setProperty("sceneWeather", weather)
        for frame in range(4 if args.frames else 1):
            window.setProperty("sceneFrame", frame)
            settle(window, 450 if frame == 0 else 120)
            image = window.grabWindow()
            target = args.out_dir / f"{name}-{frame}.png"
            if image.isNull() or not image.save(str(target)):
                raise RuntimeError(f"Could not save {target}")
            captures.append({"case": name, "frame": frame, "path": str(target.resolve()),
                             "width": image.width(), "height": image.height()})
        print(f"{name}: {time.perf_counter() - start:.2f}s")
    (args.out_dir / "capture-report.json").write_text(
        json.dumps({"captures": captures, "qml_warnings": warnings}, indent=2), encoding="utf-8")
    write_gallery(args.out_dir, captures)
    if warnings:
        print("\n".join(warnings), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
