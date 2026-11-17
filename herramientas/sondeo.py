"""Sondeo temporal: legitimados de una causa en la Corte Constitucional (se borra después)."""
import base64, json, re
from urllib.parse import quote
import requests

S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
BASE = "https://buscador.corteconstitucional.gob.ec/buscador-externo/"
H = {"Content-Type": "application/json; charset=utf-8", "Origin": "https://buscador.corteconstitucional.gob.ec", "Referer": BASE + "principal"}

def cifrar(v):
    return json.dumps({"dato": base64.b64encode(quote(json.dumps(v, separators=(",", ":"), ensure_ascii=False), safe="-_.!~*'()").encode()).decode()})

html = S.get(BASE + "principal", timeout=40).text
src = re.findall(r'src="([^"]+)"', html)
rt = S.get(BASE + [s for s in src if "runtime" in s][0], timeout=40).text
todo = S.get(BASE + [s for s in src if "main" in s][0], timeout=40).text
for cid, h in re.findall(r'(\d+):"([0-9a-f]{12,20})"', rt):
    todo += "\n" + S.get(f"{BASE}{cid}.{h}.js", timeout=40).text
for patron in [r"obtenerLegitimadosExpediente\(", r"obtenerFichaSentencia\("]:
    for m in list(re.finditer(patron, todo))[:3]:
        print(f"CTX[{patron}]:", todo[max(0, m.start()-500): m.end()+500].replace("\n", " "))

for cuerpo in [{"idCausa": 104154}, {"idcausa": 104154}, {"id": 104154}, {"idCausa": 104154, "idActuacion": 583330}]:
    r = S.post(BASE + "rest/api/expedienteLegitimado/100_EXPEDNTE_LGTMDO", data=cifrar(cuerpo), headers=H, timeout=40)
    print("\nLEGITIMADO", cuerpo, r.status_code, r.text[:1200])
for cuerpo in [{"id": 9903}, {"idResolucion": 9903}, {"idSentencia": 9903}]:
    r = S.post(BASE + "rest/api/sentencia/100_OBT_FCHA_SNTNCA", data=cifrar(cuerpo), headers=H, timeout=40)
    print("\nFICHA", cuerpo, r.status_code, r.text[:1500])
