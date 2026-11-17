"""Sondeo temporal: muestra cómo están armados los buscadores (se borra después)."""
import re
import requests
from urllib.parse import urljoin

S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"

def get(url, **kw):
    try:
        return S.get(url, timeout=40, **kw)
    except requests.exceptions.SSLError:
        return S.get(url, timeout=40, verify=False, **kw)

PAL = r"(api|rest|servicio|buscar|busqueda|search|sentencia|consulta|query|juris|filtro|ficha|documento|descarg|pdf|elastic|solr|graphql)"

def analizar_js(js, etiqueta):
    print(f"--- {etiqueta} ({len(js)} bytes)")
    cad = set(re.findall(r'["\'`]([^"\'`\s<>]{3,160})["\'`]', js))
    utiles = sorted(c for c in cad if ("/" in c or "http" in c) and re.search(PAL, c, re.I)
                    and not c.startswith(("M", "m0", "@")) and "svg" not in c)
    for c in utiles[:120]:
        print("  STR:", c)
    for patron in [r"\.(post|get|put)\s*\(", r"environment", r"apiUrl|urlApi|baseUrl|urlBase|URL_API|backend", r"https?://"]:
        for m in list(re.finditer(patron, js))[:8]:
            print(f"  CTX[{patron[:12]}]:", js[max(0, m.start()-120): m.end()+200].replace("\n", " "))

def sondear(nombre, url, max_archivos=12):
    print(f"\n######## {nombre}: {url}")
    r = get(url)
    base = r.url
    pendientes = [urljoin(base, s) for s in re.findall(r'<script[^>]+src="([^"]+)"', r.text)]
    vistos = set()
    while pendientes and len(vistos) < max_archivos:
        u = pendientes.pop(0)
        if u in vistos or "googletag" in u or "polyfills" in u:
            continue
        vistos.add(u)
        js = get(u).text
        if len(js) < 400:
            print("  PEQUEÑO", u, js)
        for imp in re.findall(r'(?:import|from)\s*\(?\s*["\'](\.?/?[^"\']+\.js)["\']', js):
            pendientes.append(urljoin(u, imp))
        analizar_js(js, u)
    for extra in ["assets/config.json", "assets/env.json", "assets/environment.json", "config.json", "env.js"]:
        try:
            rr = get(urljoin(base, extra))
            if rr.status_code == 200 and len(rr.text) < 5000 and "<html" not in rr.text.lower():
                print("  EXTRA", extra, rr.text[:800])
        except Exception:
            pass

def sondear_ro():
    print("\n######## Registro Oficial ?s=")
    r = get("https://www.registroficial.gob.ec/?s=1964-22-EP")
    t = r.text
    i = t.find("1964-22-EP", 2000)
    print("len", len(t), "pos", i)
    print(t[max(0, i-3000): i+800] if i > 0 else t[-4000:])

sondear("Corte Constitucional", "https://buscador.corteconstitucional.gob.ec/buscador-externo/principal", 4)
sondear("Corte Nacional", "https://busquedasentencias.cortenacional.gob.ec/", 15)
sondear_ro()
