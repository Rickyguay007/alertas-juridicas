"""Sondeo temporal: consulta real al buscador de la Corte Constitucional (se borra después)."""
import base64, json
from urllib.parse import quote
import requests

S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
BASE = "https://buscador.corteconstitucional.gob.ec/buscador-externo/"

def cifrar(v):
    return json.dumps({"dato": base64.b64encode(quote(json.dumps(v, separators=(",", ":"), ensure_ascii=False), safe="-_.!~*'()").encode()).decode()})

def criterio(**cambios):
    c = {"numSentencia": "", "numeroCausa": "", "textoSentencia": "", "motivo": "", "metadata": "", "subBusqueda": "",
         "tipoLegitimado": 0, "legitimados": "", "tipoAcciones": [], "materias": [], "intereses": [], "decisiones": [],
         "jueces": [], "derechoDemandado": [], "derechosTratado": [], "derechosVulnerado": [], "temaEspecificos": [],
         "conceptos": [], "fechaNotificacion": "", "fechaDecision": "", "sort": "", "precedenteAprobado": "",
         "precedentePropuesto": "", "tipoNormas": [], "asuntos": [], "analisisMerito": "", "novedad": "", "merito": "",
         "paginacion": {"page": 1, "pageSize": 3, "total": 0, "contar": True}}
    c.update(cambios)
    return c

S.get(BASE + "principal", timeout=40)
url = BASE + "rest/api/sentencia/100_BUSCR_SNTNCIA"
for c in [criterio(textoSentencia="impuesto a la renta", sort="relevancia"),
          criterio(numSentencia="1964-22-EP/26", sort="desc"),
          criterio(numeroCausa="1964-22-EP", sort="desc")]:
    r = S.post(url, data=cifrar(c), headers={"Content-Type": "application/json; charset=utf-8",
                                             "Origin": "https://buscador.corteconstitucional.gob.ec",
                                             "Referer": BASE + "principal"}, timeout=40)
    print("\n>>", c["textoSentencia"] or c["numSentencia"] or c["numeroCausa"], r.status_code)
    try:
        d = r.json()
        print("mensaje:", d.get("mensaje"), "| total:", d.get("totalFilas"))
        for item in (d.get("dato") or [])[:2]:
            print(json.dumps(item, ensure_ascii=False)[:2500])
    except Exception:
        print(r.text[:1500])
