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
for patron in [r"metadata", r"this\.criterioBusqueda=", r"criterioBusqueda\.subBusqueda", r"criterioBusqueda\.textoSentencia="]:
    for m in list(re.finditer(patron, todo))[:4]:
        print(f"CTX[{patron}]:", todo[max(0, m.start()-400): m.end()+700].replace("\n", " "))

def cifrar(v):
    return json.dumps({"dato": base64.b64encode(quote(json.dumps(v, separators=(",", ":"), ensure_ascii=False), safe="-_.!~*'()").encode()).decode()})

url = BASE + "rest/api/sentencia/100_BUSCR_SNTNCIA"
for criterio in [
    {"textoSentencia": "impuesto a la renta", "numSentencia": "", "numeroCausa": "", "sort": "relevancia",
     "paginacion": {"page": 1, "pageSize": 5, "total": 0, "contar": True}, "tipoAcciones": [], "jueces": [], "decisiones": []},
    {"textoSentencia": "", "numSentencia": "1964-22-EP/26", "numeroCausa": "", "sort": "desc",
     "paginacion": {"page": 1, "pageSize": 5, "total": 0, "contar": True}, "tipoAcciones": [], "jueces": [], "decisiones": []},
]:
    r = S.post(url, data=cifrar(criterio), headers={"Content-Type": "application/json; charset=utf-8",
                                                    "Origin": "https://buscador.corteconstitucional.gob.ec",
                                                    "Referer": BASE + "principal"}, timeout=40)
    print("\n>>", criterio["textoSentencia"] or criterio["numSentencia"], r.status_code, r.headers.get("content-type"))
    print(r.text[:2500])
