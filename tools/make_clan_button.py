"""Draw the in-game clan buttons (templates/img/clan_button_<lang>.png and
clan_challenge_button_<lang>.png).

"Clan" is emblem 3 of the clan window (templates/js/clan_overlay.js); "Retar
clan" is a red shield with two crossed swords (own art). Each has its word
under it in the game's outlined white lettering, shrunk to fit. It is drawn on a
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
CHALLENGE_LABELS = {'es': 'Retar clan', 'en': 'Challenge', 'pt-BR': 'Desafiar'}
CHALLENGE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 46" width="48" height="55">'
    '<path d="M20 2L37 8v14c0 11-8 19-17 22C11 41 3 33 3 22V8z" fill="#b3261e" stroke="#3b2410" stroke-width="2"/>'
    '<path d="M20 5l14 5v12c0 9-6 16-14 19C12 38 6 31 6 22V10z" fill="none" stroke="#f4d77a" stroke-width="1.2" opacity=".85"/>'
    '<g stroke="#3b2410" stroke-width=".8" stroke-linejoin="round">'
    '<path d="M11 10l15 17-1.6 1.6L9.4 11.6 9 9.6z" fill="#fff6d8"/>'
    '<path d="M29 10L14 27l1.6 1.6L30.6 11.6 31 9.6z" fill="#fff6d8"/>'
    '<path d="M22.5 25.5l5.5 5.5M17.5 25.5L12 31" stroke="#f4d77a" stroke-width="2.6" stroke-linecap="round"/>'
    '<path d="M27.2 32.6l1.8-1.8M12.8 32.6L11 30.8" stroke="#3b2410" stroke-width="2.4" stroke-linecap="round"/>'
    '</g></svg>')
WIDTH, HEIGHT = 60, 72


def shield_svg():
    out = subprocess.run(['node', '-e', "process.stdout.write(require('./templates/js/clan_overlay.js').emblemSvg(3, 48))"],
                         cwd=ROOT, capture_output=True, text=True, encoding='utf-8', check=True).stdout
    return out.replace('<svg ', '<svg xmlns="http://www.w3.org/2000/svg" ', 1)


def page(svg, labels):
    return """<!DOCTYPE html><meta charset="utf-8"><pre id="out">pending</pre><script>
const svg = %s, labels = %s, W = %d, H = %d, out = {};
function fit(c, text) {
  let size = 15;
  do { c.font = "bold " + size + "px 'Trebuchet MS', sans-serif"; size -= 1; } while (c.measureText(text).width > W - 6 && size > 9);
}
const image = new Image();
image.onload = () => {
  for (const [lang, text] of Object.entries(labels)) {
    const canvas = document.createElement("canvas");
    canvas.width = W; canvas.height = H;
    const c = canvas.getContext("2d");
    c.shadowColor = "rgba(0,0,0,.55)"; c.shadowBlur = 3; c.shadowOffsetY = 2;
    c.drawImage(image, (W - 48) / 2, 0, 48, 55);
    c.shadowColor = "transparent";
    fit(c, text); c.textAlign = "center"; c.textBaseline = "alphabetic";
    c.lineJoin = "round"; c.lineWidth = 4; c.strokeStyle = "#2b1a0b";
    c.strokeText(text, W / 2, H - 4); c.fillStyle = "#ffffff"; c.fillText(text, W / 2, H - 4);
    out[lang] = canvas.toDataURL("image/png");
  }
  document.getElementById("out").textContent = JSON.stringify(out);
};
image.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
</script>""" % (json.dumps(svg), json.dumps(labels, ensure_ascii=False), WIDTH, HEIGHT)


def draw(svg, labels, prefix):
    with tempfile.TemporaryDirectory() as directory:
        html = Path(directory) / 'button.html'
        html.write_text(page(svg, labels), encoding='utf-8')
        result = subprocess.run([BROWSER, '--headless=new', '--disable-gpu', f'--user-data-dir={directory}/profile',
                                 '--virtual-time-budget=5000', '--dump-dom', html.as_uri()],
                                capture_output=True, text=True, encoding='utf-8', timeout=120)
    images = json.loads(re.search(r'<pre id="out">(.*?)</pre>', result.stdout, re.S).group(1).replace('&quot;', '"'))
    for lang, data in images.items():
        target = ROOT / 'templates' / 'img' / f'{prefix}_{lang}.png'
        target.write_bytes(base64.b64decode(data.split(',', 1)[1]))
        print('wrote', target.relative_to(ROOT))


def main():
    if not BROWSER:
        raise SystemExit('Chrome or Edge is needed to draw the buttons.')
    draw(shield_svg(), LABELS, 'clan_button')
    draw(CHALLENGE_SVG, CHALLENGE_LABELS, 'clan_challenge_button')


if __name__ == '__main__':
    main()
