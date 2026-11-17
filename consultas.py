#!/usr/bin/env python3
"""
Responde las búsquedas que le escribes al bot en Telegram.

GitHub lo corre cada 20 minutos (de 6:00 a 23:00 hora de Ecuador): lee los mensajes
pendientes, busca y contesta. Por eso la respuesta puede tardar hasta unos 20 minutos.

Qué entiende:
  /cc texto o número   -> sentencias de la Corte Constitucional (ej. /cc impuesto a la renta, /cc 1964-22-EP/26)
  /ro texto o número   -> ediciones del Registro Oficial (ej. /ro NAC-DGERCGC26, /ro 17811-2018-00449)
  texto sin comando    -> busca en las dos fuentes
  más                  -> respondiendo a un mensaje de resultados, trae la página siguiente
  /ayuda               -> instrucciones

Prueba sin Telegram:  CONSULTA="impuesto a la renta" python consultas.py
"""

import html
import logging
import os
import re
import sys
import time

import requests

import alertas

POR_PAGINA = 5
log = logging.getLogger("consultas")
RE_ENCABEZADO = re.compile(r"🔎 (CC|RO) «(.+?)» · pág\. (\d+)")
RE_JUICIO = re.compile(r"\b\d{5}-\d{4}-\d{3,5}\b")
NUMEROS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

AYUDA = """🤖 <b>¿Cómo buscar?</b>

Escríbeme lo que necesitas y te respondo en unos minutos (reviso los mensajes cada 20 minutos, de 6:00 a 23:00).

👨‍⚖️ <b>/cc</b> + texto o número → sentencias de la Corte Constitucional
   • <code>/cc anticipo impuesto a la renta</code>
   • <code>/cc 1964-22-EP/26</code> (sentencia) o <code>/cc 1964-22-EP</code> (caso)

📰 <b>/ro</b> + texto o número → Registro Oficial
   • <code>/ro NAC-DGERCGC26-00000021</code>
   • <code>/ro catamayo patentes</code>
   • <code>/ro 17811-2018-00449</code> (fallos de la Corte Nacional publicados en la Edición Jurídica)
   En el Registro Oficial funcionan mejor los números o 1 a 3 palabras clave.

✍️ Si escribes sin comando, busco en las dos.
➡️ Para ver más resultados, <b>responde</b> a mi mensaje con la palabra <b>más</b>.

ℹ️ El buscador de la Corte Nacional está protegido con captcha, así que sus fallos los busco a través de la Edición Jurídica del Registro Oficial."""


def esc(t):
    return html.escape(t or "", quote=False)


def limpiar_consulta(texto):
    """El buscador de la Corte solo acepta letras, números, tildes, @, punto, guion y barra."""
    texto = re.sub(r"[^\w\sáéíóúüñÁÉÍÓÚÜÑ@.\-/]", " ", texto or "")
    return re.sub(r"\s+", " ", texto).strip()


def buscar_cc(consulta, pagina=1):
    q = consulta.strip()
    if alertas.RE_SENTENCIA_CC.match(q.upper()):
        total, res = alertas.cc_buscar(num_sentencia=q.upper(), pagina=pagina, por_pagina=POR_PAGINA)
    elif alertas.RE_CAUSA_CC.match(q.upper()):
        total, res = alertas.cc_buscar(num_causa=q.upper(), pagina=pagina, por_pagina=POR_PAGINA)
    else:
        total, res = alertas.cc_buscar(texto=q, pagina=pagina, por_pagina=POR_PAGINA)
    lineas = [f"👨‍⚖️ <b>Corte Constitucional</b>\n🔎 CC «{esc(q)}» · pág. {pagina}",
              f"📊 {total} resultado(s)"]
    if not res:
        lineas.append("\n😕 No encontré sentencias con esa búsqueda. Prueba con otras palabras o con el número del caso.")
        return lineas, False
    for i, r in enumerate(res[:POR_PAGINA]):
        f = alertas.cc_ficha(r)
        bloque = [f"\n{NUMEROS[i]} <b>{esc(f['numero'])}</b>" + (f" · {esc(f['tipo'])}" if f["tipo"] else "")]
        datos = " · ".join(x for x in [f"📅 {f['fecha']}" if f["fecha"] else "",
                                         f"⚖️ {f['decision']}" if f["decision"] else ""] if x)
        if datos:
            bloque.append(esc(datos))
        if f["juez"]:
            bloque.append(f"🧑‍⚖️ Ponente: {esc(f['juez'])}")
        if f["accionante"]:
            bloque.append(f"👤 Accionante: {esc(f['accionante'])}")
        if f["motivo"]:
            bloque.append(f"📝 {esc(alertas.recortar(f['motivo'], 450))}")
        if f["pdf"]:
            bloque.append(f'🔗 <a href="{html.escape(f["pdf"], quote=True)}">Ver sentencia (PDF)</a>')
        lineas.append("\n".join(bloque))
        time.sleep(0.3)
    hay_mas = total > pagina * POR_PAGINA
    return lineas, hay_mas


def buscar_ro(consulta, pagina=1):
    q = consulta.strip()
    resultados = alertas.ro_buscar(q)
    total = len(resultados)
    trozo = resultados[(pagina - 1) * POR_PAGINA: pagina * POR_PAGINA]
    lineas = [f"📰 <b>Registro Oficial</b>\n🔎 RO «{esc(q)}» · pág. {pagina}", f"📊 {total} edición(es) encontradas"]
    if not trozo:
        lineas.append("\n😕 No encontré publicaciones con esa búsqueda.")
        return lineas, False
    for i, r in enumerate(trozo):
        titulo = " ".join(x for x in [r["edicion"], r["numero"].replace("Año II - ", "").replace("Año I - ", "")] if x)
        bloque = [f"\n{NUMEROS[i]} <b>{esc(titulo)}</b>"]
        if r["fecha"]:
            bloque.append(f"📅 {esc(r['fecha'])}")
        if r["extracto"]:
            bloque.append(f"📝 {esc(alertas.recortar(r['extracto'], 380))}")
        if r["pdf"]:
            bloque.append(f'🔗 <a href="{html.escape(r["pdf"], quote=True)}">Ver PDF</a>')
        lineas.append("\n".join(bloque))
    return lineas, total > pagina * POR_PAGINA


def responder(texto, texto_respondido=""):
    """Devuelve la lista de mensajes (HTML) que hay que enviar."""
    t = (texto or "").strip()
    n = alertas.norm(t)
    if not t:
        return []
    if n in ("/start", "/ayuda", "/help", "ayuda", "hola", "/ayuda@", "menu", "/menu") or n.startswith(("/start", "/ayuda", "/help")):
        return [AYUDA]
    if n in ("mas", "más", "/mas", "/más", "siguiente", "ver mas"):
        m = RE_ENCABEZADO.search(texto_respondido or "")
        if not m:
            return ["➡️ Para ver más resultados, <b>responde</b> a mi mensaje de resultados (mantén presionado el mensaje → Responder) y escribe <b>más</b>."]
        fuente, consulta, pagina = m.group(1), html.unescape(m.group(2)), int(m.group(3)) + 1
        lineas, hay_mas = (buscar_cc if fuente == "CC" else buscar_ro)(consulta, pagina)
        return [unir(lineas, hay_mas)]

    comando = ""
    m = re.match(r"^/(cc|ro)(?:@\w+)?\s*(.*)$", t, flags=re.I | re.S)
    if m:
        comando, t = m.group(1).lower(), m.group(2)
    consulta = limpiar_consulta(t)
    if len(consulta) < 2:
        return ["✍️ Escribe qué quieres buscar después del comando, por ejemplo: <code>/cc acción de protección despido</code>"]

    mensajes, sin_resultados = [], []
    fuentes = []
    if comando == "cc" or (not comando and not RE_JUICIO.search(consulta)):
        fuentes.append(("cc", buscar_cc, "la Corte Constitucional"))
    if comando == "ro" or not comando:
        fuentes.append(("ro", buscar_ro, "el Registro Oficial"))
    for clave, funcion, nombre in fuentes:
        try:
            lineas, hay_mas = funcion(consulta)
        except Exception as e:  # noqa: BLE001
            log.exception("Fallo en %s", clave)
            mensajes.append(f"⚠️ No pude consultar {nombre} ahora ({esc(str(e)[:120])}). Intenta más tarde.")
            continue
        if "😕" in lineas[-1] and not comando:
            sin_resultados.append(nombre)
            continue
        mensajes.append(unir(lineas, hay_mas))
    if not mensajes:
        mensajes.append(f"😕 No encontré nada sobre «{esc(consulta)}» en {' ni en '.join(sin_resultados)}. "
                        "Prueba con otras palabras o con el número exacto.")
    return mensajes


def unir(lineas, hay_mas):
    texto = "\n".join(lineas)
    if hay_mas:
        texto += "\n\n➡️ Responde a este mensaje con <b>más</b> para ver la página siguiente."
    return texto


def partir(texto, limite=3900):
    """Telegram acepta hasta 4096 caracteres por mensaje."""
    if len(texto) <= limite:
        return [texto]
    partes, actual = [], ""
    for bloque in texto.split("\n\n"):
        if len(actual) + len(bloque) + 2 > limite and actual:
            partes.append(actual)
            actual = bloque
        else:
            actual = f"{actual}\n\n{bloque}" if actual else bloque
    if actual:
        partes.append(actual)
    return partes


class Telegram:
    def __init__(self, token, chat_id):
        self.url = f"https://api.telegram.org/bot{token}/"
        self.chat_id = str(chat_id)

    def llamar(self, metodo, **datos):
        r = requests.post(self.url + metodo, data=datos, timeout=40)
        return r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else {}

    def enviar(self, texto, responder_a=None):
        for parte in partir(texto):
            datos = {"chat_id": self.chat_id, "text": parte, "parse_mode": "HTML", "disable_web_page_preview": "true"}
            if responder_a:
                datos["reply_to_message_id"] = responder_a
                datos["allow_sending_without_reply"] = "true"
            codigo, _ = self.llamar("sendMessage", **datos)
            if codigo != 200:
                datos.pop("parse_mode")
                datos["text"] = html.unescape(re.sub(r"<[^>]+>", "", parte))[:4000]
                self.llamar("sendMessage", **datos)
            time.sleep(0.5)

    def escribiendo(self):
        self.llamar("sendChatAction", chat_id=self.chat_id, action="typing")


def principal():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    prueba = os.environ.get("CONSULTA", "").strip()
    if prueba:
        for m in responder(prueba):
            print("\n" + "=" * 60 + "\n" + m)
        return

    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        sys.exit("Faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID.")
    tg = Telegram(token, chat_id)
    codigo, datos = tg.llamar("getUpdates", timeout=0, allowed_updates='["message"]')
    actualizaciones = datos.get("result", []) if codigo == 200 else []
    log.info("Mensajes pendientes: %d", len(actualizaciones))
    ultimo = None
    try:
        for upd in actualizaciones:
            ultimo = upd["update_id"]
            msg = upd.get("message") or {}
            if str((msg.get("chat") or {}).get("id")) != tg.chat_id:
                continue  # el bot solo te responde a ti
            texto = msg.get("text", "")
            respondido = (msg.get("reply_to_message") or {}).get("text", "")
            # Telegram quita el formato del texto respondido; recuperamos el encabezado igual
            tg.escribiendo()
            for respuesta in responder(texto, respondido):
                tg.enviar(respuesta, responder_a=msg.get("message_id"))
    finally:
        if ultimo is not None:
            tg.llamar("getUpdates", offset=ultimo + 1, timeout=0)  # marca los mensajes como leídos


if __name__ == "__main__":
    principal()
