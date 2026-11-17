"""Sondeo temporal: muestra cómo están armados los buscadores (se borra después)."""
import re, sys, json
import requests
from urllib.parse import urljoin

S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"

def get(url, **kw):
    try:
        r = S.get(url, timeout=40, **kw)
    except requests.exceptions.SSLError:
        r = S.get(url, timeout=40, verify=False, **kw)
    return r

def sondear_spa(nombre, url):
    print(f"\n######## {nombre}: {url}")
    try:
        r = get(url)
    except Exception as e:
        print("ERROR", e); return
    print("status", r.status_code, "final", r.url, "len", len(r.text))
    print(r.text[:1500])
    scripts = re.findall(r'<script[^>]+src="([^"]+)"', r.text)
    print("SCRIPTS:", scripts)
    for src in scripts:
        u = urljoin(r.url, src)
        if any(x in u for x in ("googletag", "jquery", "polyfills", "runtime")):
            continue
        try:
            js = get(u).text
        except Exception as e:
            print("no js", u, e); continue
        print(f"--- {u} ({len(js)} bytes)")
        encontrados = set()
        for m in re.finditer(r'["\'`]((?:https?:)?//[^"\'`\s]{4,200}|/[a-zA-Z0-9_\-]*(?:api|rest|servicio|buscador|search|sentencia|consulta|query|jurisprudencia)[^"\'`\s]{0,150})["\'`]', js, re.I):
            encontrados.add(m.group(1))
        for e in sorted(encontrados)[:150]:
            print("  URL:", e)
        for palabra in ("baseUrl", "apiUrl", "urlApi", "environment", "endpoint", "/api/", "rest/"):
            for m in list(re.finditer(re.escape(palabra), js))[:6]:
                print(f"  CTX[{palabra}]:", js[max(0, m.start()-150): m.end()+250].replace("\n", " "))

def sondear_ro():
    print("\n######## Registro Oficial: búsqueda")
    for url in ["https://www.registroficial.gob.ec/?s=1964-22-EP",
                "https://www.registroficial.gob.ec/wp-json/wp/v2/posts?search=1964-22-EP&per_page=3&_fields=title,link,date,excerpt",
                "https://www.registroficial.gob.ec/wp-json/wp/v2/posts?search=tasa%20aduanera&per_page=3&_fields=title,link,date"]:
        try:
            r = get(url)
            print("\n>>", url, r.status_code, r.headers.get("content-type"))
            t = r.text
            if "json" in (r.headers.get("content-type") or ""):
                print(t[:1500])
            else:
                for m in re.finditer(r'<h2[^>]*>\s*<a href="([^"]+)"[^>]*>([^<]+)</a>', t):
                    print("  RES:", m.group(2).strip(), m.group(1))
        except Exception as e:
            print("ERROR", url, e)

sondear_spa("Corte Constitucional", "https://buscador.corteconstitucional.gob.ec/buscador-externo/principal")
sondear_spa("Corte Nacional", "https://busquedasentencias.cortenacional.gob.ec/")
sondear_ro()
