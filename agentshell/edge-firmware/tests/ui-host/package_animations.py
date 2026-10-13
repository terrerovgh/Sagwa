"""Package frames captured by production graphics.cpp; no UI redrawing."""
import argparse
import hashlib
import html
import json
from pathlib import Path
from PIL import Image

NAMES = ("idle", "look", "listen", "think", "speak", "work", "celebrate",
         "purr", "sleep", "wake", "stretch", "tilt", "voice-cancel", "stale-sensors")


def package(output, render_log):
    if "PASS: 14 animation clips; synthetic playback and ticks" not in render_log.read_text():
        raise ValueError("Animation render has not passed")
    items = []
    for name in NAMES:
        paths = sorted((output / name).glob("*.ppm"))
        if len(paths) != 60:
            raise ValueError(f"Incomplete clip: {name}")
        frames = []
        for path in paths:
            with Image.open(path) as frame:
                if frame.size != (320, 240):
                    raise ValueError("Unexpected frame size")
                frames.append(frame.convert("RGB"))
        gif = output / (name + ".gif")
        # GIF timing is quantized to 10 ms. Actual captured simulation time is
        # recorded separately; GIF playback is never a performance measurement.
        frames[0].save(gif, save_all=True, append_images=frames[1:], duration=60,
                       loop=0, optimize=False, disposal=2)
        items.append({"name": name, "file": gif.name, "frames": len(frames),
                      "simulated_step_ms": 56, "gif_step_ms": 60,
                      "sha256": hashlib.sha256(gif.read_bytes()).hexdigest()})
    manifest = {"renderer": "Production graphics.cpp and LVGL 9.4",
                "hardware_verified": False, "audio": "Synthetic playback bands",
                "source_log_sha256": hashlib.sha256(render_log.read_bytes()).hexdigest(),
                "clips": items}
    (output / "animations.json").write_text(json.dumps(manifest, indent=2) + "\n")
    cards = "".join(f'<figure><img src="{item["file"]}" alt="{html.escape(item["name"])}">'
                    f'<figcaption>{html.escape(item["name"])}</figcaption></figure>' for item in items)
    (output / "animations.html").write_text(
        '<!doctype html><html lang="es"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Sagwa · animaciones</title><style>'
        'body{background:#000;color:#fff;font:16px system-ui;margin:24px}'
        'main{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:24px}'
        'figure{margin:0}img{width:320px;max-width:100%}a{color:#fff}</style>'
        '<h1>Sagwa · rig animado</h1><p>Capturas del renderizador real con tiempo, sensores '
        'y audio sintéticos. La reproducción GIF no mide rendimiento del CoreS3.</p>'
        '<p><a href="animations.json">Manifiesto y hashes</a></p><main>' + cards + '</main></html>')
    print(f"Packaged {len(items)} animation clips")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--render-log", required=True, type=Path)
    args = parser.parse_args()
    package(args.output.resolve(), args.render_log.resolve())
