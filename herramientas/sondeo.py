"""Sondeo temporal: buscador de la Corte Constitucional (se borra después)."""
import re
import requests

S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
BASE = "https://buscador.corteconstitucional.gob.ec/buscador-externo/"

def get(url):
    try:
        return S.get(url, timeout=40)
    except requests.exceptions.SSLError:
        return S.get(url, timeout=40, verify=False)

html = get(BASE + "principal").text
runtime = [s for s in re.findall(r'src="([^"]+)"', html) if "runtime" in s][0]
rt = get(BASE + runtime).text
print("RUNTIME:", rt[:200])
mapa = re.findall(r'(\d+):"([0-9a-f]{12,20})"', rt)
print("CHUNKS:", mapa[:40])
todo = get(BASE + [s for s in re.findall(r'src="([^"]+)"', html) if "main" in s][0]).text
for cid, h in mapa[:40]:
    js = get(f"{BASE}{cid}.{h}.js").text
    todo += "\n" + js
    print("chunk", cid, len(js))
for patron in [r"https?://[a-zA-Z0-9.\-]+\.gob\.ec[^\"'`\s]*", r"recaptcha|captcha", r"\.post\(", r"apiUrl|urlApi|URL_|environment\.[a-zA-Z]+"]:
    vistos = 0
    for m in re.finditer(patron, todo, re.I):
        print(f"  CTX[{patron[:20]}]:", todo[max(0, m.start()-200): m.end()+400].replace("\n", " "))
        vistos += 1
        if vistos >= 6:
            break
