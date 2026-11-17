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

def contextos(js, patron, n=6, antes=300, despues=700):
    for m in list(re.finditer(patron, js))[:n]:
        print(f"  CTX[{patron}]:", js[max(0, m.start()-antes): m.end()+despues].replace("\n", " "))

def todos_js(url, maximo=15):
    r = get(url)
    pend = [urljoin(r.url, s) for s in re.findall(r'<script[^>]+src="([^"]+)"', r.text)]
    vistos, textos = set(), []
    while pend and len(vistos) < maximo:
        u = pend.pop(0)
        if u in vistos or "googletag" in u or "polyfills" in u:
            continue
        vistos.add(u)
        js = get(u).text
        textos.append(js)
        pend += [urljoin(u, i) for i in re.findall(r'(?:import|from)\s*\(?\s*["\'](\.?/?[^"\']+\.js)["\']', js)]
    return "\n".join(textos)

print("######## CNJ")
js = todos_js("https://busquedasentencias.cortenacional.gob.ec/")
for p in [r"MICROSERVICE_BUSCADOR_SENTENCIAS\s*:", r"buscarPorTipoBusqueda", r"grecaptcha|recaptchaToken|siteKey\s*[:=]", r"api\.funcionjudicial"]:
    contextos(js, p, n=4)

print("\n######## CC")
js = todos_js("https://buscador.corteconstitucional.gob.ec/buscador-externo/principal", 3)
for p in [r"gob\.ec", r"production\s*:", r"recaptcha", r"http\.post\(", r"busqueda"]:
    contextos(js, p, n=5, antes=250, despues=450)

print("\n######## RO búsqueda")
for q in ["1964-22-EP", "contencioso tributario", "Catamayo"]:
    t = get("https://www.registroficial.gob.ec/?s=" + q).text
    i = t.find("cards_container_post_imagen_search")
    print(f"\n>> q={q} len={len(t)}")
    print(t[i:i+3500] if i > 0 else "SIN CONTENEDOR")
    print("PAGINACION:", re.findall(r'href="([^"]*page/\d+/\?s=[^"]*)"', t)[:4])
