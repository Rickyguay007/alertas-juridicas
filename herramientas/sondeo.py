"""Sondeo temporal: consulta real al buscador de la Corte Constitucional (se borra después)."""
import base64, json, re
from urllib.parse import quote
import requests

S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
BASE = "https://buscador.corteconstitucional.gob.ec/buscador-externo/"

def get(url):
    return S.get(url, timeout=40)

html = get(BASE + "principal").text
src = re.findall(r'src="([^"]+)"', html)
rt = get(BASE + [s for s in src if "runtime" in s][0]).text
todo = get(BASE + [s for s in src if "main" in s][0]).text
for cid, h in re.findall(r'(\d+):"([0-9a-f]{12,20})"', rt):
    todo += "\n" + get(f"{BASE}{cid}.{h}.js").text
import itertools
for patron in [r"intercept\(", r"[\"']metadata[\"']|\.metadata\b|metadata:", r"btoa\(", r"setHeaders|headers\.set\("]:
    n = 0
    for m in re.finditer(patron, todo):
        ctx = todo[max(0, m.start()-300): m.end()+600].replace("\n", " ")
        if "ngMetadataName" in ctx or "this.metadata.flags" in ctx or "prop__metadata" in ctx or "metadata.predicate" in ctx or "metadata.read" in ctx:
            continue
        print(f"CTX[{patron[:20]}]:", ctx)
        n += 1
        if n >= 8:
            break

def cifrar(v):
    return json.dumps({"dato": base64.b64encode(quote(json.dumps(v, separators=(",", ":"), ensure_ascii=False), safe="-_.!~*'()").encode()).decode()})

url = BASE + "rest/api/sentencia/100_BUSCR_SNTNCIA"
for criterio in [
    {"sort": "relevancia", "numSentencia": "", "numeroCausa": "", "textoSentencia": "impuesto a la renta",
     "legitimados": "", "fechaDecision": "", "decisiones": [], "derechoDemandado": [], "derechosTratado": [],
     "derechosVulnerado": [], "jueces": [], "tipoAcciones": [], "subBusqueda": "", "materias": [], "intereses": [],
     "temaEspecificos": [], "conceptos": [], "tipoNormas": [], "precedenteAprobado": "", "precedentePropuesto": "",
     "asuntos": [], "paginacion": {"page": 1, "pageSize": 5, "total": 0, "contar": True}},
    dict({"sort": "relevancia", "numSentencia": "", "numeroCausa": "", "textoSentencia": "impuesto a la renta",
     "legitimados": "", "fechaDecision": "", "decisiones": [], "derechoDemandado": [], "derechosTratado": [],
     "derechosVulnerado": [], "jueces": [], "tipoAcciones": [], "subBusqueda": "", "materias": [], "intereses": [],
     "temaEspecificos": [], "conceptos": [], "tipoNormas": [], "precedenteAprobado": "", "precedentePropuesto": "",
     "asuntos": [], "paginacion": {"page": 1, "pageSize": 5, "total": 0, "contar": True}}, textoSentencia='', numSentencia='1964-22-EP/26', sort='desc'),
]:
    r = S.post(url, data=cifrar(criterio), headers={"Content-Type": "application/json; charset=utf-8",
                                                    "Origin": "https://buscador.corteconstitucional.gob.ec",
                                                    "Referer": BASE + "principal"}, timeout=40)
    print("\n>>", criterio["textoSentencia"] or criterio["numSentencia"], r.status_code, r.headers.get("content-type"))
    print(r.text[:2500])
