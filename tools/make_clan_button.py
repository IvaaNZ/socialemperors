"""Draw the in-game "Clan" button art (templates/img/clan_button_<lang>.png).

The shield is emblem 3 of the clan window (templates/js/clan_overlay.js), with
the word under it in the game's outlined white lettering. It is drawn on a
canvas in headless Chrome or Edge (no image library needed):

    .venv/Scripts/python tools/make_clan_button.py
"""

import base64
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from test_clan_overlay_browser import BROWSER  # noqa: E402

LABELS = {'es': 'Clan', 'en': 'Clan', 'pt-BR': 'Clã'}
WIDTH, HEIGHT = 60, 72


def shield_svg():
    out = subprocess.run(['node', '-e', "process.stdout.write(require('./templates/js/clan_overlay.js').emblemSvg(3, 48))"],
                         cwd=ROOT, capture_output=True, text=True, encoding='utf-8', check=True).stdout
    return out.replace('<svg ', '<svg xmlns="http://www.w3.org/2000/svg" ', 1)


def page(svg, labels):
    return """<!DOCTYPE html><meta charset="utf-8"><pre id="out">pending</pre><script>
const svg = %s, labels = %s, W = %d, H = %d, out = {};
const image = new Image();
image.onload = () => {
  for (const [lang, text] of Object.entries(labels)) {
    const canvas = document.createElement("canvas");
    canvas.width = W; canvas.height = H;
    const c = canvas.getContext("2d");
    c.shadowColor = "rgba(0,0,0,.55)"; c.shadowBlur = 3; c.shadowOffsetY = 2;
    c.drawImage(image, (W - 48) / 2, 0, 48, 55);
    c.shadowColor = "transparent";
    c.font = "bold 15px 'Trebuchet MS', sans-serif"; c.textAlign = "center"; c.textBaseline = "alphabetic";
    c.lineJoin = "round"; c.lineWidth = 4; c.strokeStyle = "#2b1a0b";
    c.strokeText(text, W / 2, H - 4); c.fillStyle = "#ffffff"; c.fillText(text, W / 2, H - 4);
    out[lang] = canvas.toDataURL("image/png");
  }
  document.getElementById("out").textContent = JSON.stringify(out);
};
image.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
</script>""" % (json.dumps(svg), json.dumps(labels, ensure_ascii=False), WIDTH, HEIGHT)


def main():
    if not BROWSER:
        raise SystemExit('Chrome or Edge is needed to draw the button.')
    with tempfile.TemporaryDirectory() as directory:
        html = Path(directory) / 'button.html'
        html.write_text(page(shield_svg(), LABELS), encoding='utf-8')
        result = subprocess.run([BROWSER, '--headless=new', '--disable-gpu', f'--user-data-dir={directory}/profile',
                                 '--virtual-time-budget=5000', '--dump-dom', html.as_uri()],
                                capture_output=True, text=True, encoding='utf-8', timeout=120)
    images = json.loads(re.search(r'<pre id="out">(.*?)</pre>', result.stdout, re.S).group(1).replace('&quot;', '"'))
    for lang, data in images.items():
        target = ROOT / 'templates' / 'img' / f'clan_button_{lang}.png'
        target.write_bytes(base64.b64decode(data.split(',', 1)[1]))
        print('wrote', target.relative_to(ROOT))


if __name__ == '__main__':
    main()
