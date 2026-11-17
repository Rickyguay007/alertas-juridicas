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
src = re.findall(r'src="([^"]+)"', html)
rt = get(BASE + [s for s in src if "runtime" in s][0]).text
todo = get(BASE + [s for s in src if "main" in s][0]).text
for cid, h in re.findall(r'(\d+):"([0-9a-f]{12,20})"', rt):
    todo += "\n" + get(f"{BASE}{cid}.{h}.js").text

print("API STRINGS:")
for s in sorted(set(re.findall(r'["\'`]([^"\'`\s]*api/v\d[^"\'`\s]*)["\'`]', todo)))[:80]:
    print("  ", s)
print("CODIGOS:")
for s in sorted(set(re.findall(r'["\'`](\d{2,3}_[A-Z0-9_]{3,40})["\'`]', todo)))[:120]:
    print("  ", s)
for patron in [r"postRequest\(", r"getRequest\(", r"basePath\s*=", r"storage/api"]:
    n = 0
    for m in re.finditer(patron, todo):
        ctx = todo[max(0, m.start()-250): m.end()+250].replace("\n", " ")
        if "encodeParams" in ctx and patron.startswith("postRequest"):
            continue
        print(f"  CTX[{patron}]:", ctx)
        n += 1
        if n >= 10:
            break
