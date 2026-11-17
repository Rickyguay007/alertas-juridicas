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

vistos = set()
for patron in [r"buscarSentencia\(", r"parametroBusqueda\.[a-zA-Z]+\s*=", r"parametroBusqueda=\{", r"esTextoValidoParaBusqueda\("]:
    n = 0
    for m in re.finditer(patron, todo):
        clave = m.start() // 300
        if clave in vistos:
            continue
        vistos.add(clave)
        print(f"  CTX[{patron[:25]}]:", todo[max(0, m.start()-500): m.end()+900].replace("\n", " "))
        n += 1
        if n >= 8:
            break
