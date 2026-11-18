#!/usr/bin/env python3
"""
Alertas jurídicas diarias por Telegram (Ecuador).

Revisa cada mañana:
  - Registro Oficial: Registro Oficial, Suplementos, Edición Constitucional, Edición Jurídica y
    Edición Especial (de esta última solo lo de los cantones elegidos en CANTONES_GAD).
  - Corte Nacional de Justicia: resoluciones con fuerza de ley y precedentes obligatorios.
  - Corte Constitucional: sentencias publicadas en la Edición Constitucional y, si está
    disponible, las notas de relatoría de su página web.
Las resoluciones del SRI, SERCOP, SENAE, etc. se detectan cuando salen en el Registro
Oficial, que es cuando entran en vigencia.

Uso:
  python alertas.py               -> revisa y envía el boletín a Telegram
  python alertas.py --prueba      -> revisa y muestra el boletín en pantalla, sin enviar ni guardar
  python alertas.py --diagnostico -> envía a Telegram un informe de qué pudo leer de cada fuente

Necesita las variables de entorno TELEGRAM_TOKEN y TELEGRAM_CHAT_ID
(en GitHub se guardan como secretos del repositorio).
"""

import datetime as dt
import html
import json
import logging
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ============================================================================
# CONFIGURACIÓN (puedes cambiar estas listas sin tocar el resto del programa)
# ============================================================================

# Enviar un mensaje corto aunque no haya novedades (sirve para saber que el bot sigue vivo).
ENVIAR_SIN_NOVEDADES = True

# La primera vez que corre, cuántos días hacia atrás revisa en el Registro Oficial.
DIAS_PRIMERA_VEZ = 2

# Máximo de "otras normas" (instituciones no prioritarias) que se listan por boletín.
MAX_OTRAS_NORMAS = 25

# Gobiernos locales (GAD): solo se avisa de lo que mencione estos cantones o parroquias.
# Escríbelos en minúsculas, entre comillas y separados por comas. Ejemplo: ["catamayo", "loja"]
# Déjalo vacío así [] si no quieres recibir nada de GADs.
CANTONES_GAD = ["catamayo"]

# Cuántas páginas del listado de suplementos revisar (en días de mucha publicación salen 7 u 8).
PAGINAS_SUPLEMENTO = 3

# Algunas páginas del Estado tienen certificados SSL incompletos. Si es True, cuando la
# conexión segura falla se reintenta sin verificar el certificado. Solo se leen páginas
# públicas y no se envía ningún dato, así que el riesgo es bajo.
REINTENTAR_SIN_VERIFICAR_SSL = True

# Instituciones que siempre aparecen arriba con ⭐ (texto en minúsculas y sin tildes).
INSTITUCIONES_PRIORITARIAS = {
    "servicio de rentas internas": "SRI",
    "servicio nacional de aduana": "SENAE",
    "servicio nacional de contratacion publica": "SERCOP",
    "superintendencia de companias": "Supercías",
    "procuraduria general del estado": "PGE",
    "contraloria general del estado": "Contraloría",
    "junta de politica y regulacion financiera": "Junta Financiera",
    "ministerio de economia y finanzas": "MEF",
    "comite de comercio exterior": "COMEX",
    "unidad de analisis financiero": "UAFE",
    "ministerio del trabajo": "Trabajo",
    "ministerio de trabajo": "Trabajo",
    "superintendencia de bancos": "Superbancos",
    "presidencia de la republica": "Presidencia",
    "asamblea nacional": "Asamblea",
    "funcion legislativa": "Asamblea",
    "corte nacional de justicia": "CNJ",
    "corte constitucional": "CC",
    "consejo de la judicatura": "Judicatura",
}

# Publicaciones de trámite que se omiten (texto en minúsculas y sin tildes).
RUIDO = [
    "personeria juridica", "personalidad juridica", "estatuto", "club deportivo",
    "clubes deportivos", "iglesia", "se delega", "delegacion", "delegaciones", "se delegan",
    "condecoracion", "plan anual de la politica", "papp", "plan operativo anual",
    "planificacion operativa", "estudio de impacto ambiental", "licencia ambiental",
    "autorizacion administrativa ambiental", "norma tecnica ecuatoriana", "nte inen",
    "disuelta y liquidada", "en liquidacion", "perito", "se designa", "subroga",
    "convenio basico de funcionamiento", "campana nacional estrategica de vacunacion",
    "periodos de veda", "embarcaciones pesqueras", "parque automotor",
    "especificacion tecnica ecuatoriana", "ete inen", "se conoce el contenido del informe",
    "informe de actividades",
]

# Si la institución no es prioritaria, solo se avisa si el texto tiene alguna de estas palabras.
PALABRAS_NORMATIVAS = [
    "se expide", "se expiden", "se reforma", "reforma", "reglamento", "instructivo",
    "normativa", "norma ", "normas ", "se deroga", "deroga", "se establece", "se regula",
    "codificacion", "procedimiento", "requisitos", "tarifa", "tasa", "arancel", "impuesto",
    "ley ", "lineamientos", "directrices", "manual", "politica publica",
]

# Materias: (nombre, emoji, palabras clave). Se asigna la primera que coincida.
MATERIAS = [
    ("Tributario", "💰", ["tribut", "impuesto", "retencion en la fuente", "contribuyente", "sri ",
                          "facturacion", "rentas internas", "anticipo", "iva ", "ice ",
                          "pago indebido", "determinacion tributaria"]),
    ("Aduanero", "🚢", ["aduan", "arancel", "senae", "mercancia", "importacion", "exportacion",
                        "comercio exterior", "copci", "salvaguard"]),
    ("Contratación pública", "🏗️", ["contratacion publica", "sercop", "compras publicas",
                                     "losncp", "contratista", "catalogo electronico",
                                     "subasta inversa", "pliego"]),
    ("Laboral", "👷", ["laboral", "trabajador", "despido", "jubilac", "remuneracion", "salario",
                       "seguridad social", "iess", "sindical", "desahucio", "codigo del trabajo"]),
    ("Societario", "🏢", ["superintendencia de companias", "societari", "accionista",
                          "mercado de valores", "companias"]),
    ("Financiero", "🏦", ["financier", "monetari", "banco", "seguros", "cooperativa", "uafe",
                          "lavado de activos", "credito"]),
    ("Penal", "🚔", ["penal", "delito", "coip", "prision", "fiscalia"]),
    ("Administrativo", "🏛️", ["contencioso administrativo", "servidor publico", "losep",
                              "contraloria", "administrativ"]),
    ("Familia y civil", "👪", ["alimentos", "ninez", "adolescen", "divorcio", "posesori",
                               "prescripcion extraordinaria", "civil"]),
    ("Ambiental y minero", "🌿", ["ambient", "minero", "mineria", "hidrocarbur"]),
    ("Procesal", "📑", ["casacion", "cogep", "procesal", "citacion", "recurso de"]),
    ("Constitucional", "⚖️", ["constitucional", "accion extraordinaria", "accion de proteccion",
                              "incumplimiento", "habeas", "dictamen"]),
]

# ============================================================================
# A partir de aquí no hace falta tocar nada
# ============================================================================

RO_BASE = "https://www.registroficial.gob.ec"
CNJ_RESOLUCIONES = "https://www.cortenacional.gob.ec/resoluciones-con-fuerza-de-ley/"
CNJ_PRECEDENTES = "https://www.cortenacional.gob.ec/precedentes-jurisprudenciales-obligatorios/"
CC_FEED = "https://www.corteconstitucional.gob.ec/feed/"

EDICIONES_RO = [
    {"clave": "ro", "nombre": "Registro Oficial", "producto": RO_BASE + "/245427-2/",
     "slugs": ["registro-oficial", "registros-oficiales"], "buscar": "registro", "tipo": "normativa",
     "titulo": "registro oficial", "paginas": 1},
    {"clave": "sup", "nombre": "Suplemento", "producto": RO_BASE + "/255776-2/",
     "slugs": ["suplemento", "suplementos"], "buscar": "suplemento", "tipo": "normativa",
     "titulo": "suplemento", "paginas": PAGINAS_SUPLEMENTO},
    {"clave": "const", "nombre": "Edición Constitucional", "producto": RO_BASE + "/267099-2/",
     "slugs": ["ediciones-constitucionales", "edicion-constitucional"], "buscar": "constitucional",
     "tipo": "constitucional", "titulo": "edicion constitucional", "paginas": 2},
    {"clave": "esp", "nombre": "Edición Especial", "producto": RO_BASE + "/261974-2/",
     "slugs": ["ediciones-especiales", "edicion-especial"], "buscar": "especial",
     "tipo": "especial", "titulo": "edicion especial", "paginas": 3},
    {"clave": "jur", "nombre": "Edición Jurídica", "producto": RO_BASE + "/266381-2/",
     "slugs": ["ediciones-juridicas", "edicion-juridica", "ediciones-juridica"], "buscar": "jur",
     "tipo": "juridica", "titulo": "edicion juridica", "paginas": 1},
]

ARCHIVO_ESTADO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "estado.json")
ZONA_EC = dt.timezone(dt.timedelta(hours=-5))

MESES_CORTOS = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7,
                "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12}
MESES_LARGOS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                "septiembre", "octubre", "noviembre", "diciembre"]
DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

TIPOS_CAUSA_CC = {
    "EP": "Acción extraordinaria de protección", "IN": "Acción pública de inconstitucionalidad",
    "IS": "Acción de incumplimiento de sentencia", "AN": "Acción por incumplimiento",
    "CN": "Consulta de norma", "JP": "Revisión de garantías (jurisprudencia vinculante)",
    "JH": "Revisión de hábeas corpus", "JD": "Revisión de hábeas data",
    "JI": "Revisión de acceso a la información", "EE": "Estado de excepción",
    "RC": "Reforma constitucional", "CP": "Consulta popular", "TI": "Tratado internacional",
    "DN": "Desclasificación de información", "IA": "Inconstitucionalidad de actos administrativos",
    "EI": "Acción extraordinaria contra decisiones de justicia indígena",
    "OP": "Objeción presidencial", "IO": "Interpretación constitucional",
}

log = logging.getLogger("alertas")

SESION = requests.Session()
SESION.headers.update({
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "es-EC,es;q=0.9",
})


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def norm(texto):
    """Minúsculas y sin tildes, para comparar."""
    texto = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def limpiar(texto):
    return re.sub(r"\s+", " ", (texto or "")).strip()


def recortar(texto, maximo=320):
    texto = limpiar(texto)
    if len(texto) <= maximo:
        return texto
    corte = texto[:maximo].rsplit(" ", 1)[0]
    return corte.rstrip(",;:.") + "…"


def esc(texto):
    return html.escape(texto or "", quote=False)


def hoy_ec():
    return dt.datetime.now(ZONA_EC).date()


def fecha_larga(fecha):
    return f"{DIAS_SEMANA[fecha.weekday()]} {fecha.day} de {MESES_LARGOS[fecha.month - 1]} de {fecha.year}"


def descargar(url, aceptar_404=False):
    """Descarga una página y devuelve el texto, o lanza una excepción."""
    ultimo_error = None
    for intento in range(3):
        try:
            try:
                r = SESION.get(url, timeout=45)
            except requests.exceptions.SSLError:
                if not REINTENTAR_SIN_VERIFICAR_SSL:
                    raise
                log.warning("Certificado SSL no válido en %s, reintento sin verificar", url)
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                r = SESION.get(url, timeout=45, verify=False)
            if r.status_code == 404 and aceptar_404:
                return None
            r.raise_for_status()
            if not r.encoding or r.encoding.lower() in ("iso-8859-1", "ascii"):
                r.encoding = "utf-8"
            return r.text
        except Exception as e:  # noqa: BLE001
            ultimo_error = e
            time.sleep(3 * (intento + 1))
    raise RuntimeError(f"No se pudo abrir {url}: {ultimo_error}")


def sopa(texto_html):
    return BeautifulSoup(texto_html, "html.parser")


_PATRONES = {}


def contiene(texto_norm, palabra):
    """Busca la palabra al inicio de una palabra del texto ('iva ' no coincide con 'normativa')."""
    if palabra not in _PATRONES:
        fin = r"\b" if palabra.endswith(" ") else ""
        _PATRONES[palabra] = re.compile(r"\b" + re.escape(palabra.strip()) + fin)
    return bool(_PATRONES[palabra].search(texto_norm))


def clasificar_materia(*textos, defecto="General"):
    t = norm(" ".join(t for t in textos if t)) + " "
    for nombre, emoji, palabras in MATERIAS:
        if any(contiene(t, p) for p in palabras):
            return f"{nombre} {emoji}"
    if defecto == "Constitucional":
        return "Constitucional ⚖️"
    return defecto


def etiqueta_prioritaria(institucion, tipo=""):
    t = norm(institucion)
    for clave, etiqueta in INSTITUCIONES_PRIORITARIAS.items():
        if clave in t:
            return etiqueta
    tt = norm(tipo)
    if tt.startswith("decreto"):
        return "Presidencia"
    if tt.startswith("ley"):
        return "Asamblea"
    return None


def es_ruido(texto):
    t = norm(texto)
    return any(p in t for p in RUIDO)


def es_normativo(texto):
    t = norm(texto) + " "
    return any(contiene(t, p) for p in PALABRAS_NORMATIVAS)


SIGLAS = {"SRI", "SENAE", "SERCOP", "IESS", "BIESS", "ARCSA", "ARCOTEL", "ARCONEL", "ARCERNNR",
          "INEN", "SEPS", "UAFE", "MAE", "MAGP", "CNJ", "GAD", "EP", "ONG", "BCE", "CFN", "SENADI",
          "SENESCYT", "INEC", "MEF", "MDT", "MIES", "MIDUVI", "MTOP", "SNAI", "CNE", "TCE", "CPCCS",
          "COMEX", "AGROCALIDAD", "DMQ", "LOSNCP", "COPCI", "SCVS", "SB", "PGE", "URS", "IEPS",
          "INEVAL", "MDEP", "MPCEI", "SPDP", "ICCA", "CNEL", "CELEC", "ANT", "ECU", "S.A", "S.A.S", "C.A",
          "E.P", "DMQ", "EPMMOP", "GAD"}


def titulo_institucion(nombre):
    """MINISTERIO DE ECONOMÍA -> Ministerio de Economía (respeta las siglas conocidas)."""
    nombre = limpiar(nombre).rstrip(":").strip()
    # El sitio a veces pega palabras: "MINISTERIODE AMBIENTE"
    nombre = re.sub(r"\b(MINISTERIO|AGENCIA|SERVICIO|SECRETAR[IÍ]A|SUPERINTENDENCIA|CONSEJO|INSTITUTO)(DEL|DE)\b", r"\1 \2", nombre)
    if not nombre:
        return ""
    menores = {"de", "del", "la", "las", "lo", "los", "y", "e", "el", "en", "para", "por", "a", "al"}
    palabras = []
    for i, p in enumerate(nombre.split(" ")):
        bajo = p.lower()
        limpio = p.strip("(),.-–")
        if i > 0 and bajo in menores:
            palabras.append(bajo)
        elif limpio.upper() in SIGLAS or (p.isupper() and len(limpio) <= 4 and not re.search(r"[AEIOUÁÉÍÓÚ]", limpio)):
            palabras.append(p.upper())
        else:
            palabras.append(p[:1].upper() + p[1:].lower())
    return " ".join(palabras)


@dataclass
class Novedad:
    seccion: str            # "cc", "cnj", "prioritaria", "otras"
    institucion: str
    numero: str
    resumen: str
    materia: str
    enlace: str
    origen: str = ""        # p. ej. "Segundo Suplemento RO Nº 410 · 16/11/2026"
    actores: str = ""
    tipo_causa: str = ""
    etiqueta: str = ""
    detalle: str = ""       # p. ej. "⚖️ Desestimar · Ponente: Karla Andrade"


@dataclass
class Resultado:
    novedades: list = field(default_factory=list)
    vistos_nuevos: dict = field(default_factory=dict)   # fuente -> [ids]
    omitidas: int = 0
    diagnostico: list = field(default_factory=list)     # (fuente, ok, detalle)
    errores: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Buscador de la Corte Constitucional (sentencias con resumen, decisión y partes)
# ---------------------------------------------------------------------------

CC_BUSCADOR = "https://buscador.corteconstitucional.gob.ec/buscador-externo/"
CC_PDF = "https://esacc.corteconstitucional.gob.ec/storage/api/v1/10_DWL_FL/"
RE_SENTENCIA_CC = re.compile(r"^\d{1,4}-\d{2}-[A-Z]{2,3}/\d{2}$")
RE_CAUSA_CC = re.compile(r"^\d{1,4}-\d{2}-[A-Z]{2,3}$")


def _cc_post(ruta, cuerpo):
    """El buscador espera el JSON codificado en base64 dentro de {"dato": ...}."""
    import base64
    from urllib.parse import quote
    texto = json.dumps(cuerpo, separators=(",", ":"), ensure_ascii=False)
    datos = json.dumps({"dato": base64.b64encode(quote(texto, safe="-_.!~*'()").encode()).decode()})
    r = SESION.post(CC_BUSCADOR + "rest/api/" + ruta, data=datos, timeout=45, headers={
        "Content-Type": "application/json; charset=utf-8",
        "Origin": "https://buscador.corteconstitucional.gob.ec", "Referer": CC_BUSCADOR + "principal"})
    r.raise_for_status()
    return r.json()


def cc_buscar(texto="", num_sentencia="", num_causa="", pagina=1, por_pagina=5):
    """Devuelve (total, [resoluciones]) del buscador de sentencias de la Corte Constitucional."""
    criterio = {"numSentencia": num_sentencia, "numeroCausa": num_causa, "textoSentencia": texto, "motivo": "",
                "metadata": "", "subBusqueda": "", "tipoLegitimado": 0, "legitimados": "", "tipoAcciones": [],
                "materias": [], "intereses": [], "decisiones": [], "jueces": [], "derechoDemandado": [],
                "derechosTratado": [], "derechosVulnerado": [], "temaEspecificos": [], "conceptos": [],
                "fechaNotificacion": "", "fechaDecision": "", "sort": "relevancia" if texto else "desc",
                "precedenteAprobado": "", "precedentePropuesto": "", "tipoNormas": [], "asuntos": [],
                "analisisMerito": "", "novedad": "", "merito": "",
                "paginacion": {"page": 1, "pageSize": 20, "total": 0, "contar": True}}
    # El servidor siempre trae páginas de 20, así que pedimos la página de 20 que contiene
    # los resultados solicitados y recortamos.
    inicio = (pagina - 1) * por_pagina
    criterio["paginacion"]["page"] = inicio // 20 + 1
    datos = _cc_post("sentencia/100_BUSCR_SNTNCIA", criterio)
    todos = [d.get("resolucion") or {} for d in (datos.get("dato") or [])]
    desde = inicio % 20
    return datos.get("totalFilas") or 0, todos[desde:desde + por_pagina]


def cc_legitimados(id_causa):
    """{'activos': [...], 'pasivos': [...]} de una causa."""
    salida = {"activos": [], "pasivos": []}
    if not id_causa:
        return salida
    for p in _cc_post("expedienteLegitimado/100_EXPEDNTE_LGTMDO", {"id": id_causa}).get("dato") or []:
        tipo = norm((p.get("tipoLegitimado") or {}).get("nombre", ""))
        nombre = limpiar(p.get("nombreCompleto", ""))
        if not nombre:
            continue
        if "activo" in tipo:
            salida["activos"].append(nombre)
        elif "pasivo" in tipo:
            salida["pasivos"].append(nombre)
    return salida


def cc_pdf(resolucion):
    import base64
    for doc in resolucion.get("documento") or []:
        if doc.get("repositorio") == "HDFS" and doc.get("uuid"):
            ruta = json.dumps({"carpeta": doc.get("carpeta"), "uuid": doc["uuid"]}, separators=(",", ":"))
            return CC_PDF + base64.b64encode(ruta.encode()).decode()
        if str(doc.get("uuid", "")).startswith("http"):
            return doc["uuid"]
    return ""


def cc_ficha(resolucion, con_partes=True):
    """Datos listos para mostrar de una resolución del buscador."""
    causa = (resolucion.get("causa") or [{}])[0]
    fecha = ""
    if resolucion.get("fechadecision"):
        fecha = dt.datetime.fromtimestamp(resolucion["fechadecision"] / 1000, ZONA_EC).strftime("%d/%m/%Y")
    partes = {"activos": [], "pasivos": []}
    if con_partes:
        try:
            partes = cc_legitimados(resolucion.get("idcausa"))
        except Exception:  # noqa: BLE001
            pass
    activos = partes["activos"]
    return {
        "numero": resolucion.get("numero", ""),
        "tipo": (causa.get("tipoaccion") or "").capitalize(),
        "fecha": fecha,
        "decision": ", ".join(d.get("resumendecision", "").capitalize() for d in resolucion.get("decision") or [] if d.get("resumendecision")),
        "juez": ", ".join(titulo_institucion(j.get("nombrecompleto", "")) for j in resolucion.get("juez") or []),
        "motivo": limpiar(html.unescape(html.unescape(resolucion.get("motivo") or "")).replace("\u037e", ";")).replace(";;", ";").replace(";;", ";"),
        "accionante": ", ".join(titulo_institucion(a) for a in activos[:2]) + (f" y {len(activos) - 2} más" if len(activos) > 2 else ""),
        "pdf": cc_pdf(resolucion),
    }


def ro_buscar(texto):
    """Búsqueda del sitio del Registro Oficial: [{edicion, numero, fecha, extracto, pdf}]."""
    from urllib.parse import quote_plus
    s = sopa(descargar(f"{RO_BASE}/?s={quote_plus(texto)}"))
    resultados = []
    for tarjeta in s.select(".card__item_post_imagen_search"):
        def texto_de(selector):
            el = tarjeta.select_one(selector)
            return limpiar(el.get_text(" ")) if el else ""
        parrafos = [limpiar(p.get_text(" ")) for p in tarjeta.select("p.txt_fecha_post_imagen")]
        enlace = tarjeta.select_one("a.cta_post_imagen_search, a[href]")
        resultados.append({
            "edicion": texto_de(".card__title_post_imagen"),
            "numero": texto_de(".card__title_numero_imagen"),
            "fecha": parrafos[0] if parrafos else "",
            "extracto": limpiar((parrafos[-1] if len(parrafos) > 2 else "").lstrip(".… ")),
            "pdf": enlace["href"] if enlace else "",
        })
    return resultados


# ---------------------------------------------------------------------------
# Registro Oficial
# ---------------------------------------------------------------------------

RE_EDICION = re.compile(
    r"(?:(primer|primero|segundo|tercer|tercero|cuarto|quinto|sexto|septimo|octavo|noveno|decimo)\s+)?"
    r"(suplemento|registro oficial|edicion constitucional|edicion juridica|edicion especial)"
    r"(?:\s+al\s+registro\s+oficial)?\s*(?:no\.?|n[º°o]\.?|nro\.?)\s*(\d+)")
RE_NUMERO = re.compile(r"n[º°o]\.?\s*(\d+)")
RE_FECHA_POST = re.compile(r"(\d{1,2})\s+(ene|feb|mar|abr|may|jun|jul|ago|sep|set|oct|nov|dic)[a-z]*\.?\s+(\d{4})")


def clave_edicion(texto):
    """'Segundo Suplemento No. 410' -> ('suplemento', 'segundo', '410')."""
    m = RE_EDICION.search(norm(texto))
    if not m:
        return None
    ordinal = (m.group(1) or "primer").replace("primero", "primer").replace("tercero", "tercer")
    tipo = m.group(2)
    if tipo != "suplemento":
        ordinal = "primer"
    return (tipo, ordinal, m.group(3))


def nombre_edicion(clave):
    tipo, ordinal, numero = clave
    nombres = {"suplemento": "Suplemento", "registro oficial": "Registro Oficial",
               "edicion constitucional": "Edición Constitucional",
               "edicion juridica": "Edición Jurídica", "edicion especial": "Edición Especial"}
    base = nombres.get(tipo, tipo.title())
    if tipo == "suplemento":
        ordinal_bonito = {"septimo": "Séptimo", "decimo": "Décimo"}.get(ordinal, ordinal.title())
        return f"{ordinal_bonito} Suplemento del RO Nº {numero}"
    if tipo == "registro oficial":
        return f"Registro Oficial Nº {numero}"
    return f"{base} Nº {numero}"


def leer_fecha_post(texto):
    m = RE_FECHA_POST.search(norm(texto))
    if not m:
        return None
    try:
        return dt.date(int(m.group(3)), MESES_CORTOS[m.group(2)], int(m.group(1)))
    except ValueError:
        return None


def listar_posts(texto_html, base_url, tipo_esperado=None):
    """Devuelve [(titulo, url, fecha)] de una página de categoría de WordPress."""
    s = sopa(texto_html)
    posts = []

    def sirve(titulo):
        clave = clave_edicion(titulo)
        return bool(clave) and (tipo_esperado is None or clave[0] == tipo_esperado)

    contenedores = s.find_all("article") or []
    if contenedores:
        for art in contenedores:
            h = art.find(["h2", "h1", "h3"])
            a = h.find("a", href=True) if h else art.find("a", href=True)
            if not a:
                continue
            titulo = limpiar(a.get_text())
            if not sirve(titulo):
                continue
            posts.append((titulo, urljoin(base_url, a["href"]), leer_fecha_post(art.get_text(" "))))
    else:
        for h in s.find_all(["h2", "h3"]):
            a = h.find("a", href=True)
            if not a:
                continue
            titulo = limpiar(a.get_text())
            if not sirve(titulo):
                continue
            meta = h.find_next(string=lambda t: bool(t and RE_FECHA_POST.search(norm(t))))
            posts.append((titulo, urljoin(base_url, a["href"]), leer_fecha_post(str(meta or ""))))
    vistos, unicos = set(), []
    for p in posts:
        if p[1] not in vistos:
            vistos.add(p[1])
            unicos.append(p)
    return unicos


def singular_tipo(texto):
    """'ediciones constitucionales' -> 'edicion constitucional'."""
    t = norm(texto)
    for canonico, raiz in [("suplemento", "suplemento"), ("registro oficial", "registro"),
                           ("edicion constitucional", "constitucional"), ("edicion juridica", "juridica"),
                           ("edicion especial", "especial")]:
        if raiz in t:
            return canonico
    return t


def mapa_pdfs(texto_html):
    """De la página de producto: clave de edición -> (enlace al PDF, fecha)."""
    s = sopa(texto_html)
    mapa = {}
    for a in s.find_all("a", href=True):
        if "descargar" not in norm(a.get_text()):
            continue
        previos = []
        for cadena in a.find_all_previous(string=True, limit=25):
            c = limpiar(cadena)
            if c:
                previos.append(c)
        numero, tipo_ordinal, fecha = None, None, None
        for c in previos:  # del más cercano al más lejano
            n = norm(c)
            if fecha is None:
                fecha = leer_fecha_post(c)
            if numero is None:
                m = RE_NUMERO.search(n)
                if m:
                    numero = m.group(1)
            if tipo_ordinal is None:
                m = re.search(r"(?:(primer|segundo|tercer|cuarto|quinto|sexto|septimo|octavo|noveno|decimo)\s+)?"
                              r"(suplementos?|registros? oficial(?:es)?|edicion(?:es)? constitucional(?:es)?|"
                              r"edicion(?:es)? juridicas?|edicion(?:es)? especial(?:es)?)\b", n)
                if m and "pagina" not in n:
                    tipo_ordinal = (singular_tipo(m.group(2)), m.group(1) or "primer")
            if numero and tipo_ordinal:
                break
        if numero and tipo_ordinal:
            tipo, ordinal = tipo_ordinal
            if tipo != "suplemento":
                ordinal = "primer"
            mapa.setdefault((tipo, ordinal, numero), (a["href"], fecha))
    return mapa


def urls_probables(clave):
    """Direcciones que suele usar el Registro Oficial para cada edición (plan B si falla el listado)."""
    tipo, ordinal, numero = clave
    if tipo == "suplemento":
        if ordinal == "primer":
            return [f"{RO_BASE}/suplemento-no-{numero}/", f"{RO_BASE}/primer-suplemento-no-{numero}/",
                    f"{RO_BASE}/suplemento-al-registro-oficial-no-{numero}/"]
        return [f"{RO_BASE}/{ordinal}-suplemento-no-{numero}/",
                f"{RO_BASE}/{ordinal}-suplemento-al-registro-oficial-no-{numero}/"]
    slug = tipo.replace(" ", "-")
    return [f"{RO_BASE}/{slug}-no-{numero}/", f"{RO_BASE}/{slug}-n-{numero}/", f"{RO_BASE}/{slug}-{numero}/"]


def texto_sumario(texto_html):
    """Saca las líneas del sumario de la página de una edición."""
    s = sopa(texto_html)
    for basura in s(["script", "style", "noscript", "nav", "header", "footer", "form", "img"]):
        basura.decompose()
    contenedor = None
    for selector in [".et_pb_post_content", ".entry-content", "article .et_pb_text_inner",
                     ".et_pb_post", "article", "#main-content", "body"]:
        el = s.select_one(selector)
        if el and len(el.get_text(strip=True)) > 40:
            contenedor = el
            break
    if contenedor is None:
        return []
    for quitar in contenedor.select("h1, .post-meta, .et_post_meta_wrapper, .et_pb_title_meta_container, .sidebar, #sidebar"):
        quitar.decompose()
    # Salto de línea solo donde termina un párrafo o hay un <br>, para no partir
    # "<strong>NAC-DGERCGC26-0001</strong> Se expide…" en dos líneas.
    for br in contenedor.find_all("br"):
        br.replace_with("\n")
    for bloque_html in contenedor.find_all(["p", "div", "li", "h2", "h3", "h4", "h5", "h6", "tr", "td"]):
        bloque_html.append("\n")
    lineas = []
    for linea in contenedor.get_text("").split("\n"):
        linea = limpiar(linea)
        if not linea:
            continue
        if norm(linea) in ("buscar", "seleccionar pagina"):
            break
        if re.match(r"^por .+\|", linea):
            continue
        lineas.append(linea)
    return lineas


RE_TIPO = re.compile(
    r"^(ACUERDOS?( MINISTERIALES?)?|RESOLUCION(ES)?|DECRETOS?( EJECUTIVOS?)?|ORDENANZAS?( .*)?|"
    r"SENTENCIAS?( .*)?|DICTAMEN(ES)?( .*)?|AUTOS?|AVISOS? JUDICIAL(ES)?|CIRCULAR(ES)?|OFICIOS?|"
    r"INSTRUMENTOS? INTERNACIONAL(ES)?|RESUMEN(ES)? DE CAUSAS?|FE DE ERRATAS|CONVENIOS?|"
    r"REGLAMENTOS?|LEY(ES)?|RESOLUCIONES Y .*|EXTRACTOS?|CONSULTAS?( ABSUELTAS)?)$")


def es_mayusculas(linea):
    letras = [c for c in linea if c.isalpha()]
    return bool(letras) and sum(c.isupper() for c in letras) / len(letras) > 0.85


def separar_codigo(linea):
    """'NAC-DGERCGC26-00000021 Se expiden...' -> ('NAC-DGERCGC26-00000021', 'Se expiden...')."""
    partes = linea.split(None, 1)
    if len(partes) < 2 and not re.search(r"\d{5}-\d{4}-\d{4,5}", linea):
        return None
    token = partes[0].rstrip(",;")
    resto = partes[1] if len(partes) > 1 else ""
    if not re.search(r"\d", token):
        return None
    if not re.fullmatch(r"[A-Z0-9ÁÉÍÓÚÑ./\-]+", token):
        return None
    if not ("-" in token or "/" in token or (token.isdigit() and len(token) <= 5)):
        return None
    return token, resto


def analizar_sumario(lineas):
    """Convierte las líneas del sumario en una lista de publicaciones."""
    items = []
    funcion, tipo, institucion, encabezado_grupo = "", "", "", ""
    pendiente = []
    codigo_suelto = ""

    def soltar_pendiente():
        nonlocal pendiente
        if not pendiente:
            return
        texto = " ".join(pendiente)
        pendiente = []
        m = re.match(r"^(LEY|CODIGO|CÓDIGO|REGLAMENTO|DECRETO|NORMA)\b", texto)
        if m:
            clase = m.group(1)
            if clase in ("LEY", "CODIGO", "CÓDIGO"):
                emisor, clase_tipo = "ASAMBLEA NACIONAL", "LEY"
            elif clase == "DECRETO":
                emisor, clase_tipo = "PRESIDENCIA DE LA REPÚBLICA", "DECRETO"
            else:
                emisor, clase_tipo = institucion or "PRESIDENCIA DE LA REPÚBLICA", tipo or clase
            items.append({"funcion": funcion, "tipo": clase_tipo, "institucion": emisor,
                          "codigo": "", "texto": texto.capitalize(), "grupo": ""})
        elif items:
            items[-1]["texto"] += " " + texto

    for linea in lineas:
        linea = re.sub(r"\s*\.{3,}\s*\d*\s*$", "", linea).strip()  # quita "......... 25"
        if not linea or norm(linea) in ("sumario:", "sumario", "pags.", "pags", "pag."):
            continue
        if re.fullmatch(r"[\d\s.]+", linea):
            continue
        # Un código solo en su línea (p. ej. en negrita) se une con la línea siguiente
        if " " not in linea and re.fullmatch(r"[A-Z0-9ÁÉÍÓÚÑ./\-]*\d[A-Z0-9ÁÉÍÓÚÑ./\-]*", linea) and ("-" in linea or "/" in linea):
            soltar_pendiente()
            codigo_suelto = linea
            continue
        if codigo_suelto:
            if not linea.endswith(":"):
                linea = f"{codigo_suelto} {linea}"
            codigo_suelto = ""
        codigo = separar_codigo(linea)
        if es_mayusculas(linea) and not codigo:
            n = norm(linea)
            if n.startswith(("funcion ", "gobiernos autonomos", "gobierno autonomo")) and not linea.endswith(":"):
                soltar_pendiente()
                funcion, tipo, institucion, encabezado_grupo = linea, "", "", ""
                continue
            if linea.endswith(":"):
                cabecera = limpiar(linea[:-1])
                cabecera_norm = norm(cabecera).upper()
                if RE_TIPO.match(cabecera_norm):
                    if pendiente:
                        institucion = " ".join(pendiente)
                        pendiente = []
                    tipo, encabezado_grupo = cabecera, ""
                else:
                    institucion = " ".join(pendiente + [cabecera])
                    pendiente, encabezado_grupo = [], ""
                continue
            pendiente.append(linea)
            continue
        soltar_pendiente()
        if codigo:
            items.append({"funcion": funcion, "tipo": tipo, "institucion": institucion,
                          "codigo": codigo[0], "texto": codigo[1], "grupo": encabezado_grupo})
            continue
        if linea.endswith(":"):
            encabezado_grupo = linea[:-1]
            continue
        if items and items[-1]["institucion"] == institucion:
            items[-1]["texto"] += " " + linea
    soltar_pendiente()
    for it in items:
        it["texto"] = limpiar(it["texto"])
    return items


def novedades_normativa(items, origen, enlace, resultado):
    for it in items:
        funcion_n, inst_n, tipo_n = norm(it["funcion"]), norm(it["institucion"]), norm(it["tipo"])
        if "gobierno" in funcion_n and "autonom" in funcion_n:
            resultado.omitidas += 1
            continue
        if "gobierno autonomo" in inst_n or inst_n.startswith(("canton ", "gad ")) or "aviso" in tipo_n or "fe de erratas" in tipo_n:
            resultado.omitidas += 1
            continue
        texto = it["texto"]
        if it["grupo"]:
            grupo = it["grupo"]
            if "clasifican" in norm(grupo):
                grupo = "Clasificación arancelaria"
            texto = f"{grupo}: {texto}"
        es_decreto = tipo_n.startswith("decreto")
        if (es_ruido(texto) and not es_decreto) or "condecoracion" in norm(texto):
            resultado.omitidas += 1
            continue
        etiqueta = etiqueta_prioritaria(it["institucion"], it["tipo"])
        if not etiqueta and not es_normativo(texto):
            resultado.omitidas += 1
            continue
        institucion = titulo_institucion(it["institucion"]) or titulo_institucion(it["tipo"]) or "Publicación"
        numero = it["codigo"] or ("Ley" if tipo_n.startswith("ley") else titulo_institucion(it["tipo"]))
        if tipo_n.startswith("decreto") and it["codigo"].isdigit():
            numero = f"Decreto Ejecutivo {it['codigo']}"
        resultado.novedades.append(Novedad(
            seccion="prioritaria" if etiqueta else "otras",
            institucion=institucion,
            numero=numero,
            resumen=recortar(texto, 300),
            materia=clasificar_materia(texto, it["institucion"]),
            enlace=enlace, origen=origen, etiqueta=etiqueta or ""))


def novedades_gad(lineas, origen, enlace, resultado):
    """Publicaciones de los GADs de los cantones elegidos en CANTONES_GAD."""
    if not CANTONES_GAD:
        return
    patrones = [(c, re.compile(r"\b" + re.escape(norm(c)) + r"\b")) for c in CANTONES_GAD]
    tipo_actual, ya = "", set()
    for i, linea in enumerate(lineas):
        linea = re.sub(r"\s*\.{3,}\s*\d*\s*$", "", linea).strip()
        if linea.endswith(":") and es_mayusculas(linea) and not any(p.search(norm(linea)) for _, p in patrones):
            tipo_actual = linea[:-1]
        encontrado = next((c for c, p in patrones if p.search(norm(linea))), None)
        if not encontrado:
            continue
        resumen = linea.lstrip("-–•· ").strip()
        if es_mayusculas(linea):  # encabezado tipo "GAD MUNICIPAL DEL CANTÓN CATAMAYO": el detalle va abajo
            siguientes = [limpiar(l) for l in lineas[i + 1:i + 3] if limpiar(l)]
            resumen = (titulo_institucion(resumen) + ": " + " ".join(siguientes)).strip(": ")
        clave = norm(resumen)[:120]
        if clave in ya:
            continue
        ya.add(clave)
        n = norm(linea)
        nivel = "Provincial" if "provincial" in n else "Parroquial" if "parroquial" in n else "Municipal"
        codigo = separar_codigo(resumen)
        resultado.novedades.append(Novedad(
            seccion="gad", institucion=f"GAD {nivel} – {encontrado.title()}",
            numero=codigo[0] if codigo else (titulo_institucion(tipo_actual) or "Publicación"),
            resumen=recortar(codigo[1] if codigo else resumen, 300),
            materia=clasificar_materia(resumen, defecto="Régimen local 🏘️"),
            enlace=enlace, origen=origen))


def novedades_constitucional(items, origen, enlace, resultado):
    for it in items:
        codigo, texto = it["codigo"], it["texto"]
        resumen = re.sub(r"^En el Caso N[o°º]\.?\s*[\w\-/]+\s*", "", texto, flags=re.I)
        resumen = re.sub(r"\s*N[o°º]\.?\s*[\d]+-\d{2}-[A-Z]{2,3}\s*$", "", resumen).strip()
        actores = ""
        m = re.search(r"Legitimad[oa]s?\s+[Aa]ctiv[oa]s?\s*:\s*(.+)$", texto)
        if m:
            actores = recortar(m.group(1), 160)
            resumen = limpiar(texto[:m.start()]).rstrip(".")
        m = re.search(r"-([A-Z]{2,3})(?:/\d+)?$", codigo)
        tipo_causa = TIPOS_CAUSA_CC.get(m.group(1), "") if m else ""
        tipo_n = norm(it["tipo"])
        institucion = "Corte Constitucional"
        if "admision" in norm(it["institucion"]) or "resumen de causa" in tipo_n:
            institucion = "Corte Constitucional – Sala de Admisión"
            if not resumen:
                resumen = "Demanda admitida a trámite"
        nov = Novedad(
            seccion="cc", institucion=institucion, numero=codigo or titulo_institucion(it["tipo"]),
            resumen=recortar(resumen or texto, 300),
            materia=clasificar_materia(texto, defecto="Constitucional"),
            enlace=enlace, origen=origen, actores=actores, tipo_causa=tipo_causa)
        if RE_SENTENCIA_CC.match(codigo or ""):
            enriquecer_con_buscador(nov, codigo)
        resultado.novedades.append(nov)


def enriquecer_con_buscador(nov, numero):
    """Completa la sentencia con el resumen, la decisión, el ponente y el accionante del buscador de la Corte."""
    try:
        _, encontrados = cc_buscar(num_sentencia=numero, por_pagina=1)
        if not encontrados:
            return
        ficha = cc_ficha(encontrados[0])
        if ficha["motivo"]:
            nov.resumen = recortar(ficha["motivo"], 420)
            nov.materia = clasificar_materia(ficha["motivo"], defecto="Constitucional")
        if ficha["accionante"] and not nov.actores:
            nov.actores = ficha["accionante"]
        detalle = []
        if ficha["decision"]:
            detalle.append(f"⚖️ {ficha['decision']}")
        if ficha["juez"]:
            detalle.append(f"Ponente: {ficha['juez']}")
        nov.detalle = " · ".join(detalle)
        if ficha["pdf"]:
            nov.enlace = ficha["pdf"]
        time.sleep(0.5)
    except Exception as e:  # noqa: BLE001
        log.warning("No pude completar %s con el buscador de la Corte: %s", numero, e)


def novedades_juridica(lineas, origen, enlace, resultado):
    """Edición Jurídica: agrupa los números de juicio por sala."""
    grupos, sala = {}, "Corte Nacional de Justicia"
    cabecera = None  # nombre de sala que puede venir partido en varias líneas
    for linea in lineas:
        n = norm(linea)
        if es_mayusculas(linea) and not re.search(r"\d{4}", linea):
            if cabecera is not None and not cabecera.endswith(":") \
                    and not n.startswith(("resolucion", "sentencia", "juicio", "autos", "funcion", "corte ")):
                cabecera += " " + linea
                sala = titulo_institucion(cabecera)
                continue
            if "sala" in n or "tribunal" in n or "corte nacional" in n:
                cabecera = linea
                sala = titulo_institucion(linea)
                continue
            cabecera = None
            continue
        cabecera = None
        juicios = re.findall(r"J?(\d{5}-\d{4}-\d{3,5}[A-Z]?)", linea)
        if juicios:
            grupos.setdefault(sala, [])
            for j in juicios:
                if j not in grupos[sala]:
                    grupos[sala].append(j)
    for sala, juicios in grupos.items():
        sala = re.sub(r"^Corte Nacional de Justicia\s+(?=Sala)", "", sala)
        lista = ", ".join(juicios[:8]) + (f" y {len(juicios) - 8} más" if len(juicios) > 8 else "")
        resultado.novedades.append(Novedad(
            seccion="cnj", institucion=sala if "corte" in norm(sala) or "tribunal" in norm(sala) else f"Corte Nacional – {sala}",
            numero=f"{len(juicios)} fallo(s) publicados",
            resumen=f"Juicios: {lista}", materia=clasificar_materia(sala, defecto="General"),
            enlace=enlace, origen=origen))


def url_categoria(edicion, diag):
    tipo = edicion["titulo"]
    for slug in edicion["slugs"]:
        url = f"{RO_BASE}/category/productos/{slug}/"
        try:
            contenido = descargar(url, aceptar_404=True)
        except Exception:  # noqa: BLE001
            contenido = None
        if contenido and listar_posts(contenido, url, tipo):
            return url, contenido
    # Plan B: preguntarle a WordPress por sus categorías
    try:
        datos = json.loads(descargar(f"{RO_BASE}/wp-json/wp/v2/categories?per_page=100&search={edicion['buscar']}"))
        for cat in datos:
            enlace = cat.get("link", "")
            if enlace:
                contenido = descargar(enlace, aceptar_404=True)
                if contenido and listar_posts(contenido, enlace, tipo):
                    return enlace, contenido
    except Exception as e:  # noqa: BLE001
        diag.append(f"categorías por wp-json no disponibles ({e})")
    return None, None


def revisar_registro_oficial(estado, desde, resultado):
    vistos = set(estado.get("vistos", {}).get("registro_oficial", []))
    nuevos_ids = []
    for edicion in EDICIONES_RO:
        if edicion["tipo"] == "especial" and not CANTONES_GAD:
            continue
        nombre_fuente = f"Registro Oficial – {edicion['nombre']}"
        notas = []
        try:
            # 1) Listado de ediciones (páginas de categoría del sitio)
            posts = []
            url_cat, primera = url_categoria(edicion, notas)
            if url_cat:
                posts = listar_posts(primera, url_cat, edicion["titulo"])
                for pagina in range(2, edicion["paginas"] + 1):
                    fechas = [p[2] for p in posts if p[2]]
                    if fechas and min(fechas) < desde:
                        break
                    try:
                        contenido = descargar(f"{url_cat.rstrip('/')}/page/{pagina}/", aceptar_404=True)
                    except Exception:  # noqa: BLE001
                        break
                    if not contenido:
                        break
                    ya = {q[1] for q in posts}
                    posts += [p for p in listar_posts(contenido, url_cat, edicion["titulo"]) if p[1] not in ya]
            else:
                notas.append("listado no disponible, uso la página de descargas")

            # 2) Página de descargas: enlaces a los PDF y, si hace falta, ediciones que el listado no trajo
            pdfs = {}
            try:
                pdfs = mapa_pdfs(descargar(edicion["producto"]))
            except Exception as e:  # noqa: BLE001
                notas.append(f"sin enlaces PDF ({e})")
            claves_listadas = {clave_edicion(p[0]) for p in posts}
            for clave, (_, fecha_pdf) in pdfs.items():
                if clave in claves_listadas or clave[0] != edicion["titulo"]:
                    continue
                if fecha_pdf is None or fecha_pdf < desde:
                    continue
                for url_probable in urls_probables(clave):
                    if url_probable in vistos:
                        break
                    try:
                        contenido = descargar(url_probable, aceptar_404=True)
                    except Exception:  # noqa: BLE001
                        contenido = None
                    if contenido and texto_sumario(contenido):
                        posts.append((nombre_edicion(clave), url_probable, fecha_pdf))
                        break

            if not posts and not pdfs:
                resultado.diagnostico.append((nombre_fuente, False, "no encontré ediciones. " + " ".join(notas)))
                resultado.errores.append(nombre_fuente)
                continue

            candidatos = [p for p in posts if p[1] not in vistos and p[1] not in nuevos_ids
                          and (p[2] is None or p[2] >= desde)]
            antes = len(resultado.novedades)
            for titulo, url_post, fecha in candidatos:
                clave = clave_edicion(titulo)
                origen = nombre_edicion(clave) + (f" · {fecha:%d/%m/%Y}" if fecha else "")
                enlace = pdfs.get(clave, (url_post, None))[0]
                try:
                    lineas = texto_sumario(descargar(url_post))
                except Exception as e:  # noqa: BLE001
                    notas.append(f"no pude abrir {titulo} ({e})")
                    continue
                if edicion["tipo"] == "juridica":
                    novedades_juridica(lineas, origen, enlace, resultado)
                elif edicion["tipo"] == "constitucional":
                    novedades_constitucional(analizar_sumario(lineas), origen, enlace, resultado)
                else:
                    novedades_normativa(analizar_sumario(lineas), origen, enlace, resultado)
                    novedades_gad(lineas, origen, enlace, resultado)
                nuevos_ids.append(url_post)
                time.sleep(1)
            detalle = (f"{len(posts)} ediciones en el listado, {len(candidatos)} nuevas, "
                       f"{len(resultado.novedades) - antes} avisos, {len(pdfs)} PDFs ubicados")
            if notas:
                detalle += ". " + "; ".join(notas)
            resultado.diagnostico.append((nombre_fuente, True, detalle))
        except Exception as e:  # noqa: BLE001
            log.exception("Fallo en %s", nombre_fuente)
            resultado.diagnostico.append((nombre_fuente, False, str(e)))
            resultado.errores.append(nombre_fuente)
    resultado.vistos_nuevos["registro_oficial"] = nuevos_ids


# ---------------------------------------------------------------------------
# Corte Nacional de Justicia
# ---------------------------------------------------------------------------

def leer_resoluciones_cnj(texto_html, base_url, marca_ruta):
    """Lista [(id, numero, descripcion, enlace)] de la página de resoluciones o precedentes."""
    s = sopa(texto_html)
    anclas = [a for a in s.find_all("a", href=True)
              if marca_ruta in a["href"] and "resoluci" in norm(a.get_text())]
    salida = []
    for i, a in enumerate(anclas):
        siguiente = anclas[i + 1] if i + 1 < len(anclas) else None
        partes = []
        for cadena in a.find_all_next(string=True):
            padre_a = cadena.find_parent("a")
            if siguiente is not None and padre_a is siguiente:
                break
            if padre_a is a:
                continue
            c = limpiar(cadena)
            if not c:
                continue
            if re.match(r"^(Resoluciones|Fallos triple reiteraci[oó]n) \d{4}", c):
                break
            partes.append(c)
            if sum(len(p) for p in partes) > 900:
                break
        numero = limpiar(a.get_text()).rstrip(":")
        descripcion = limpiar(" ".join(partes))
        descripcion = re.sub(r"^Declara como PRECEDENTE JURISPRUDENCIAL OBLIGATORIO( en materia [\w\s]+?)? el siguiente punto de derecho:\s*",
                             "Precedente obligatorio: ", descripcion, flags=re.I)
        href = a["href"]
        enlace = href if href.startswith("http") else base_url
        salida.append((href, numero, descripcion, enlace))
    return salida


def revisar_cnj(estado, primera_vez, resultado):
    vistos = set(estado.get("vistos", {}).get("cnj", []))
    nuevos_ids = []
    for nombre, url, marca, tipo in [
        ("Corte Nacional – Resoluciones con fuerza de ley", CNJ_RESOLUCIONES, "/Fuerza-de-Ley/", "Resolución con fuerza de ley"),
        ("Corte Nacional – Precedentes obligatorios", CNJ_PRECEDENTES, "/Precedentes/", "Precedente jurisprudencial obligatorio"),
    ]:
        try:
            lista = leer_resoluciones_cnj(descargar(url), url, marca)
            if not lista:
                resultado.diagnostico.append((nombre, False, "la página abrió pero no encontré resoluciones (¿cambió el diseño?)"))
                resultado.errores.append(nombre)
                continue
            nuevas = [r for r in lista if r[0] not in vistos]
            for ident, numero, descripcion, enlace in nuevas:
                nuevos_ids.append(ident)
                if primera_vez:
                    continue
                resultado.novedades.append(Novedad(
                    seccion="cnj", institucion="Corte Nacional de Justicia – Pleno",
                    numero=numero, resumen=recortar(descripcion, 350),
                    materia=clasificar_materia(descripcion, defecto="General"),
                    enlace=enlace, origen=tipo))
            resultado.diagnostico.append((nombre, True, f"{len(lista)} en la página, {len(nuevas)} nuevas"
                                          + (" (primera vez: se guardan sin avisar)" if primera_vez else "")))
        except Exception as e:  # noqa: BLE001
            resultado.diagnostico.append((nombre, False, str(e)))
            resultado.errores.append(nombre)
    resultado.vistos_nuevos["cnj"] = nuevos_ids


# ---------------------------------------------------------------------------
# Corte Constitucional (notas de relatoría en su página web)
# ---------------------------------------------------------------------------

RE_CASO_CC = re.compile(r"\b\d{1,4}-\d{2}-[A-Z]{2,3}(?:/\d{2})?\b")
TITULOS_NO_RELATORIA = ("audiencia", "sesion", "avoco", "primer tribunal", "segundo tribunal",
                        "tercer tribunal", "tribunal de sala", "condolencia", "comunicado",
                        "convocatoria", "resolucion no.", "formulario", "rendicion de cuentas")


def revisar_cc_web(estado, primera_vez, resultado):
    import xml.etree.ElementTree as ET
    nombre = "Corte Constitucional – página web"
    vistos = set(estado.get("vistos", {}).get("cc_web", []))
    nuevos_ids = []
    try:
        crudo = descargar(CC_FEED)
        inicio, fin = crudo.find("<rss"), crudo.rfind("</rss>")
        if inicio == -1 or fin == -1:
            raise RuntimeError("la página no publica un feed RSS")
        raiz = ET.fromstring(crudo[inicio:fin + len("</rss>")].encode("utf-8"))
        entradas = raiz.findall("./channel/item")
        if not entradas:
            raise RuntimeError("el feed no trae publicaciones")
        avisos = 0
        for item in entradas:
            enlace = limpiar(item.findtext("link") or "")
            ident = limpiar(item.findtext("guid") or "") or enlace
            if not ident or ident in vistos:
                continue
            nuevos_ids.append(ident)
            titulo = limpiar(html.unescape(item.findtext("title") or ""))
            if norm(titulo).startswith(TITULOS_NO_RELATORIA):
                continue
            contenido_html = (item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or "") \
                + " " + (item.findtext("description") or "")
            contenido = sopa(contenido_html)
            texto = limpiar(contenido.get_text(" "))
            casos = RE_CASO_CC.findall(titulo + " " + texto)
            relatoria = casos or re.match(r"^(se vulnera|son inconstitucional|es inconstitucional|la corte constitucional (declara|resuelve|establece|determina|se pronuncia)|no se vulnera)", norm(titulo))
            if not relatoria or primera_vez:
                continue
            pdf = ""
            for a in contenido.find_all("a", href=True):
                if "esacc.corteconstitucional" in a["href"] or a["href"].lower().endswith(".pdf"):
                    pdf = a["href"]
                    break
            resultado.novedades.append(Novedad(
                seccion="cc", institucion="Corte Constitucional – Relatoría",
                numero=", ".join(dict.fromkeys(casos)) if casos else "Nota de relatoría",
                resumen=recortar(titulo + (". " + texto if texto and norm(texto[:60]) != norm(titulo[:60]) else ""), 320),
                materia=clasificar_materia(titulo, texto, defecto="Constitucional"),
                enlace=pdf or enlace, origen="Página web de la Corte Constitucional"))
            avisos += 1
        resultado.diagnostico.append((nombre, True, f"{len(entradas)} publicaciones en el feed, {avisos} notas de sentencias"))
    except Exception as e:  # noqa: BLE001
        # Es una fuente complementaria: si falla, las sentencias igual llegan por la Edición Constitucional.
        resultado.diagnostico.append((nombre, False, f"{e} (las sentencias igual llegan por la Edición Constitucional)"))
    resultado.vistos_nuevos["cc_web"] = nuevos_ids


# ---------------------------------------------------------------------------
# Mensaje de Telegram
# ---------------------------------------------------------------------------

def bloque(nov):
    lineas = []
    estrella = " ⭐" if nov.seccion == "prioritaria" else ""
    lineas.append(f"🏛️ <b>{esc(nov.institucion)}</b>{estrella}")
    lineas.append(f"📌 <b>{esc(nov.numero)}</b>" + (f" · {esc(nov.tipo_causa)}" if nov.tipo_causa else ""))
    if nov.actores:
        lineas.append(f"👤 Accionante: {esc(nov.actores)}")
    if nov.detalle:
        lineas.append(esc(nov.detalle))
    lineas.append(f"📝 {esc(nov.resumen)}")
    lineas.append(f"🏷️ Materia: {esc(nov.materia)}")
    es_pdf = "esacc.corteconstitucional" in nov.enlace or nov.enlace.lower().endswith(".pdf")
    etiqueta_enlace = "Ver PDF" if es_pdf else "Ver publicación"
    enlace = f'<a href="{html.escape(nov.enlace, quote=True)}">{etiqueta_enlace}</a>' if nov.enlace else ""
    pie = " · ".join(x for x in [enlace, esc(nov.origen)] if x)
    if pie:
        lineas.append(f"🔗 {pie}")
    return "\n".join(lineas)


def armar_mensajes(resultado, primera_vez, fecha):
    secciones = [
        ("cc", "👨‍⚖️ <b>CORTE CONSTITUCIONAL</b>", "Corte Constitucional"),
        ("cnj", "⚖️ <b>CORTE NACIONAL DE JUSTICIA</b>", "Corte Nacional"),
        ("prioritaria", "📰 <b>REGISTRO OFICIAL · Instituciones clave</b>", "Instituciones clave"),
        ("gad", "🏘️ <b>GAD · " + esc(", ".join(c.title() for c in CANTONES_GAD)).upper() + "</b>", "GAD"),
        ("otras", "📋 <b>OTRAS NORMAS RELEVANTES</b>", "Otras normas"),
    ]
    encabezado = f"📚 <b>Boletín jurídico</b>\n🗓️ {fecha_larga(fecha).capitalize()}"
    if primera_vez:
        encabezado += "\n\n✅ ¡Tu bot quedó activado! Desde mañana te llegará este resumen cada día a las 8:30."
    total = len(resultado.novedades)
    if total == 0:
        if not ENVIAR_SIN_NOVEDADES and not primera_vez and not resultado.errores:
            return []
        texto = encabezado + "\n\n😌 Hoy no hay novedades relevantes en las fuentes revisadas."
        if resultado.omitidas:
            texto += f"\n🔕 Se omitieron {resultado.omitidas} publicaciones de trámite (estatutos, delegaciones, otros GADs…)."
        if resultado.errores:
            texto += "\n\n⚠️ No pude revisar: " + esc(", ".join(resultado.errores))
        return [texto]

    conteo = {s: sum(1 for n in resultado.novedades if n.seccion == s) for s, _, _ in secciones}
    resumen_conteo = " · ".join(f"{corto}: {conteo[s]}" for s, _, corto in secciones if conteo[s])
    bloques = [encabezado + f"\n\n🔎 {total} novedad(es) — {esc(resumen_conteo)}"]
    for clave, titulo, _ in secciones:
        grupo = [n for n in resultado.novedades if n.seccion == clave]
        if not grupo:
            continue
        if clave == "prioritaria":
            orden = list(dict.fromkeys(INSTITUCIONES_PRIORITARIAS.values()))
            grupo.sort(key=lambda n: orden.index(n.etiqueta) if n.etiqueta in orden else len(orden))
        sobrantes = 0
        if clave == "otras" and len(grupo) > MAX_OTRAS_NORMAS:
            sobrantes = len(grupo) - MAX_OTRAS_NORMAS
            grupo = grupo[:MAX_OTRAS_NORMAS]
        bloques.append(f"━━━━━━━━━━━━━━\n{titulo}")
        bloques.extend(bloque(n) for n in grupo)
        if sobrantes:
            bloques.append(f"➕ Y {sobrantes} norma(s) más en el Registro Oficial de hoy.")
    pie = []
    if resultado.omitidas:
        pie.append(f"🔕 Se omitieron {resultado.omitidas} publicaciones de trámite (estatutos, delegaciones, otros GADs…).")
    if resultado.errores:
        pie.append("⚠️ No pude revisar: " + esc(", ".join(resultado.errores)))
    if pie:
        bloques.append("\n".join(pie))

    mensajes, actual = [], ""
    for b in bloques:
        if len(actual) + len(b) + 2 > 3800 and actual:
            mensajes.append(actual)
            actual = b
        else:
            actual = f"{actual}\n\n{b}" if actual else b
    if actual:
        mensajes.append(actual)
    return mensajes


def enviar_telegram(mensajes):
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise SystemExit("Faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID (revisa los secretos del repositorio).")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for texto in mensajes:
        r = requests.post(url, data={"chat_id": chat_id, "text": texto, "parse_mode": "HTML",
                                     "disable_web_page_preview": "true"}, timeout=30)
        if r.status_code != 200:
            log.warning("Telegram rechazó el formato (%s), envío como texto simple", r.text[:200])
            plano = html.unescape(re.sub(r"<[^>]+>", "", texto))
            r = requests.post(url, data={"chat_id": chat_id, "text": plano[:4000],
                                         "disable_web_page_preview": "true"}, timeout=30)
            if r.status_code != 200:
                raise SystemExit(f"Telegram no aceptó el mensaje: {r.text[:300]}")
        time.sleep(1)


# ---------------------------------------------------------------------------
# Estado (lo ya avisado) y programa principal
# ---------------------------------------------------------------------------

def cargar_estado():
    try:
        with open(ARCHIVO_ESTADO, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def guardar_estado(estado, resultado, ahora):
    vistos = estado.setdefault("vistos", {})
    for fuente, ids in resultado.vistos_nuevos.items():
        lista = vistos.get(fuente, [])
        for i in ids:
            if i not in lista:
                lista.append(i)
        vistos[fuente] = lista[-3000:]
    estado["ultima_revision"] = ahora.isoformat(timespec="minutes")
    with open(ARCHIVO_ESTADO, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=1)


def principal():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    modo_prueba = "--prueba" in sys.argv or os.environ.get("MODO", "").lower() == "prueba"
    modo_diag = "--diagnostico" in sys.argv or os.environ.get("MODO", "").lower() == "diagnostico"

    estado = cargar_estado()
    primera_vez = not estado.get("ultima_revision")
    ahora = dt.datetime.now(ZONA_EC)
    hoy = ahora.date()

    # GitHub a veces se salta el horario, por eso hay varios turnos de respaldo en la mañana.
    # Si el boletín de hoy ya salió, los turnos automáticos siguientes no hacen nada.
    automatico = os.environ.get("GITHUB_EVENT_NAME") == "schedule"
    if automatico and not primera_vez and estado["ultima_revision"][:10] == hoy.isoformat():
        log.info("El boletín de hoy ya se envió (%s); este turno de respaldo no hace nada.", estado["ultima_revision"])
        return
    if primera_vez:
        desde = hoy - dt.timedelta(days=DIAS_PRIMERA_VEZ)
    else:
        ultima = dt.date.fromisoformat(estado["ultima_revision"][:10])
        desde = min(ultima, hoy) - dt.timedelta(days=1)

    resultado = Resultado()
    revisar_registro_oficial(estado, desde, resultado)
    revisar_cnj(estado, primera_vez, resultado)
    revisar_cc_web(estado, primera_vez, resultado)

    for fuente, ok, detalle in resultado.diagnostico:
        log.info("%s %s: %s", "OK " if ok else "ERR", fuente, detalle)

    if modo_diag:
        texto = "🩺 <b>Diagnóstico de fuentes</b>\n\n" + "\n\n".join(
            f"{'✅' if ok else '❌'} <b>{esc(f)}</b>\n{esc(d)}" for f, ok, d in resultado.diagnostico)
        texto += f"\n\n📊 Avisos que saldrían hoy: {len(resultado.novedades)} · omitidos: {resultado.omitidas}"
        mensajes = [texto[:3900]]
    else:
        mensajes = armar_mensajes(resultado, primera_vez, hoy)

    if modo_prueba:
        for m in mensajes:
            print("\n" + "=" * 60 + "\n" + m)
        return
    if mensajes:
        enviar_telegram(mensajes)
    if not modo_diag:
        guardar_estado(estado, resultado, ahora)


if __name__ == "__main__":
    principal()
