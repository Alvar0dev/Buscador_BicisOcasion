"""
enriquecedor_web.py
Búsqueda web automática para completar datos faltantes de bicicletas
cuando el scraping de detalle no los tiene.

Estrategia (en orden de fiabilidad):
  1. Ficha del producto del propio sitio (Scrapling) - mas fiable, datos reales.
  2. DuckDuckGo HTML (sin API key) - fallback general.

Solo se usa como fallback para campos críticos: peso, suspension, ano, km,
talla, bateria y motor.
"""

import re
import json
import logging
import os
import base64
from urllib.parse import urljoin
import requests
from typing import Optional, Dict, Tuple, List, Any
from pathlib import Path
from bs4 import BeautifulSoup
from models import Bicicleta
import config as cfg

log = logging.getLogger("enriquecedor")

try:
    from scrapling.fetchers import Fetcher, StealthyFetcher
    SCRAPLING_AVAILABLE = True
except ImportError:
    SCRAPLING_AVAILABLE = False

try:
    from scraper_base import crear_proxy_rotator
except Exception:
    crear_proxy_rotator = lambda: None


import threading

# ---------------------------------------------------------------------------
# Caché de fichas de detalle (tarea 12, Fase D)
# ---------------------------------------------------------------------------
CACHE_DIR = cfg.BASE_DIR / "cache"
CACHE_FILE = CACHE_DIR / "fichas_detalle.json"
_CACHE_LOCK = threading.Lock()


def _cargar_cache() -> Dict[str, dict]:
    """Carga el caché de fichas de detalle desde disco."""
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"[Caché] No se pudo leer {CACHE_FILE}: {e}")
        return {}


def _guardar_cache(cache: Dict[str, dict]) -> None:
    """Guarda el caché de fichas de detalle en disco."""
    CACHE_DIR.mkdir(exist_ok=True)
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except OSError as e:
        log.warning(f"[Caché] No se pudo escribir {CACHE_FILE}: {e}")


def _buscar_en_cache(url: str) -> Optional[dict]:
    """Busca los datos extraídos de una ficha en el caché (thread-safe)."""
    with _CACHE_LOCK:
        cache = _cargar_cache()
        return cache.get(url)


def _guardar_en_cache(url: str, datos: dict) -> None:
    """Guarda los datos extraídos de una ficha en el caché (thread-safe)."""
    with _CACHE_LOCK:
        cache = _cargar_cache()
        cache[url] = datos
        _guardar_cache(cache)


# ---------------------------------------------------------------------------
# 1. Enriquecimiento desde la ficha del propio sitio (Scrapling)
# ---------------------------------------------------------------------------

def _extraer_pares_ficha_estructurada(soup: BeautifulSoup) -> List[Tuple[str, str]]:
    """
    Extrae pares (etiqueta, valor) de la ficha técnica estructurada:
      1. Listas de definición <dt>/<dd> (Upway, PrestaShop dl.data-sheet).
      2. Tablas técnicas <tr><th>/<td> o <tr><td>/<td> (Buhobike table.caracteristicas-tecnicas-2-tablas,
         #description table, .product-features table, .data-sheet table).
      3. Atributo JSON #product-details[data-product] de PrestaShop (features).
    """
    pares: List[Tuple[str, str]] = []

    # 1. Pares <dt>/<dd>
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if not dd:
            continue
        label = dt.get_text(" ", strip=True).lower()
        val = dd.get_text(" ", strip=True)
        if label and val:
            pares.append((label, val))

    # 2. Filas de tablas técnicas (Buhobike / PrestaShop)
    tablas = soup.select(
        "table.caracteristicas-tecnicas-2-tablas, #description table, "
        "#product-details table, .product-features table, .data-sheet table, "
        ".product-description table"
    )
    for tabla in tablas:
        for tr in tabla.find_all("tr"):
            celdas = tr.find_all(["th", "td"])
            if len(celdas) >= 2:
                label = celdas[0].get_text(" ", strip=True).lower().rstrip(":")
                val = celdas[1].get_text(" ", strip=True)
                if label and val:
                    pares.append((label, val))

    # 3. Atributo JSON data-product en #product-details (PrestaShop)
    pd = soup.select_one("#product-details[data-product]")
    if pd and pd.get("data-product"):
        try:
            dp = json.loads(pd["data-product"])
            for feat in dp.get("features", []) or []:
                if isinstance(feat, dict):
                    label = str(feat.get("name", "")).strip().lower()
                    val = str(feat.get("value", "")).strip()
                    if label and val:
                        pares.append((label, val))
        except Exception:
            pass

    # 4. Listas técnicas <li> clave-valor (ej. Mammoth: <li>Batería: ...</li>, .technical-specifications li)
    elementos_li = soup.select(
        "ul.specifications li, ul.features li, .product-features li, "
        ".technical-specifications li, .tech-specs li, #specs li, "
        ".caracteristicas li, .product-attributes li, ul.data-sheet li"
    )
    for li in elementos_li:
        txt_li = li.get_text(" ", strip=True)
        if ":" in txt_li:
            partes = txt_li.split(":", 1)
            lbl = partes[0].strip().lower()
            val_li = partes[1].strip()
            if lbl and val_li and len(lbl) <= 50:
                pares.append((lbl, val_li))

    return pares


def _recolectar_urls_imagenes_ficha(soup: BeautifulSoup, url_ficha: str = "") -> List[str]:
    """
    Extrae las URLs de las fotografías de la galería de producto antes de descomponer el DOM.
    Soporta Buhobike, Bike Ocasión, Upway y Mammoth Bikes.
    """
    if soup is None:
        return []

    img_urls: List[str] = []
    palabras_excluidas = ("sello-", "logo", "icon", "avatar", "banner", "badge", ".svg", ".gif")

    def _agregar_url(raw_url: Optional[str], exigir_patron_galeria: bool = False) -> None:
        if not raw_url:
            return
        u = raw_url.strip()
        if not u or u.startswith("data:"):
            return
        if url_ficha:
            u = urljoin(url_ficha, u)
        u_low = u.lower()
        if any(p in u_low for p in palabras_excluidas):
            return
        if exigir_patron_galeria and not any(
            k in u_low for k in ("default", "large", "product", "uploads", "cdn", "shopify", "upway", "mammoth", ".jpg", ".jpeg", ".webp", ".png")
        ):
            return
        if u not in img_urls:
            img_urls.append(u)

    for img in soup.select(
        "img.js-thumb, .product-images img, ul.product-images img, "
        ".images-container img, .product-gallery img, [data-image-large-src], [data-full-size-image-url]"
    ):
        u = (
            img.get("data-image-large-src")
            or img.get("data-full-size-image-url")
            or img.get("data-src")
            or img.get("src")
        )
        _agregar_url(u, exigir_patron_galeria=True)

    if not img_urls:
        for a in soup.select("ul.product-images a.thumb, .js-thumb, a[data-image], a.js-thumb-mask"):
            u = a.get("data-image") or a.get("href")
            _agregar_url(u, exigir_patron_galeria=False)

    return img_urls[:8]


def _extraer_desde_ficha_sitio(url: str, sitio_nombre: str, km_ya_conocido: bool = False) -> dict:
    """
    Entra a la ficha de producto del sitio y extrae los campos que pueda:
    talla, bateria_wh, km, motor, cuadro_material, ano, peso_kg,
    suspension_trasera, componentes, modalidad, recorrido_mm.
    Devuelve un dict con los campos encontrados (puede estar parcialmente vacio).
    """
    detalle: dict = {}
    if not SCRAPLING_AVAILABLE:
        return detalle

    # --- Caché: verificar si ya consultamos esta ficha antes ---
    # Si la bicicleta no tiene km (ni en tarjeta ni en caché) y nunca se verificaron
    # sus imágenes con Visión IA, no cortocircuitar para poder inspeccionar la galería.
    cache_hit = _buscar_en_cache(url)
    if cache_hit:
        tiene_km_cache = _normalizar_km_existente(cache_hit.get("km")) is not None
        vision_ya_verificada = bool(cache_hit.get("km_vision_checked"))
        if km_ya_conocido or tiene_km_cache or vision_ya_verificada or not cfg.GEMINI_API_KEY:
            log.info(f"[Caché] Ficha ya consultada: {url} -> {list(cache_hit.keys())}")
            return dict(cache_hit)
        log.info(f"[Caché] Re-analizando ficha para extraer km desde imágenes: {url}")

    try:
        rotator = crear_proxy_rotator()
        kwargs_fetcher = {"impersonate": "chrome120", "timeout": 30}
        kwargs_stealth = {"headless": True, "solve_cloudflare": True, "timeout": 60}
        if rotator is not None:
            kwargs_fetcher["proxy_rotator"] = rotator
            kwargs_stealth["proxy_rotator"] = rotator

        es_buhobike = "buhobike.com" in url.lower() or sitio_nombre.lower() == "buhobike"
        if es_buhobike:
            page = StealthyFetcher.fetch(url, **kwargs_stealth)
        else:
            page = Fetcher.get(url, **kwargs_fetcher)
            if page.status != 200:
                # Fallback a stealth si el sitio tiene Cloudflare
                page = StealthyFetcher.fetch(url, **kwargs_stealth)
        if page.status != 200:
            log.warning(f"[Enriquecedor] No se pudo abrir ficha {url} (status {page.status})")
            return dict(cache_hit) if cache_hit else detalle
    except Exception as e:
        log.warning(f"[Enriquecedor] Error abriendo ficha {url}: {e}")
        return dict(cache_hit) if cache_hit else detalle

    html = str(page.html_content)
    soup = BeautifulSoup(html, "html.parser")

    # 0. Recolectar URLs de imágenes de la galería antes de descomponer nodos del DOM
    img_urls_galeria = _recolectar_urls_imagenes_ficha(soup, url_ficha=url)

    # 1. Extraer pares estructurados (<dt>/<dd>, tablas técnicas de Buhobike y data-product)
    for label, val in _extraer_pares_ficha_estructurada(soup):
        if label in ("año", "ano", "año del modelo", "temporada") and "ano" not in detalle:
            ano_dt = _extraer_ano(val)
            if ano_dt:
                detalle["ano"] = ano_dt
        elif "peso" in label and not any(x in label for x in ("embalaje", "máximo", "maximo", "ciclista")) and "peso_kg" not in detalle:
            peso_dt = _extraer_peso(f"Peso: {val}") or _extraer_peso(val)
            if peso_dt is not None:
                detalle["peso_kg"] = peso_dt
        elif ("batería" in label or "bateria" in label) and "bateria_wh" not in detalle:
            bat_dt = _extraer_bateria(val)
            if bat_dt is not None:
                detalle["bateria_wh"] = bat_dt
        elif any(k in label for k in ("salud", "soh", "estado de salud", "capacidad restante", "vida útil", "vida util")) and "bateria_salud_pct" not in detalle:
            soh_dt, _ = _extraer_salud_bateria(f"{label}: {val}")
            if soh_dt is not None:
                detalle["bateria_salud_pct"] = soh_dt
        elif any(k in label for k in ("ciclo", "ciclos", "recargas", "cargas")) and "bateria_ciclos" not in detalle:
            _, cic_dt = _extraer_salud_bateria(f"{label}: {val}")
            if cic_dt is not None:
                detalle["bateria_ciclos"] = cic_dt
        elif "talla" in label and "talla" not in detalle:
            talla_limpia = val.split(":")[0].strip() if ":" in val else val.split()[0].strip()
            if talla_limpia in ("XS", "S", "M", "L", "XL", "XXL"):
                detalle["talla"] = talla_limpia
        elif "motor" in label and "motor" not in detalle:
            detalle["motor"] = _extraer_motor(val) or val
        elif ("cuadro" in label or "material" in label) and "cuadro_material" not in detalle:
            cuadro_dt = _extraer_cuadro(val)
            if cuadro_dt:
                detalle["cuadro_material"] = cuadro_dt
        elif any(k in label for k in ("recorrido", "travel", "horquilla", "amortiguador")) and "recorrido_mm" not in detalle:
            rec_dt = _extraer_recorrido(val)
            if rec_dt:
                detalle["recorrido_mm"] = rec_dt
        elif any(k in label for k in ("kilometraje", "kilómetros", "kilometros", "odómetro", "odometro", "km", "kms")) and "km" not in detalle:
            km_dt = _extraer_km(f"Km: {val}") or _normalizar_km_existente(val)
            if km_dt is not None:
                detalle["km"] = km_dt
        if ("suspensión" in label or "suspension" in label or "amortiguador" in label) and "suspension_trasera" not in detalle:
            if "semi" in val.lower() or "rígida" in val.lower() or "hardtail" in val.lower():
                detalle["suspension_trasera"] = "no"
            elif any(k in val.lower() for k in ["doble", "total", "completa", "full", "mm", "fox", "rockshox"]):
                detalle["suspension_trasera"] = "si"

    # 2. Eliminar menús, cabeceras, pies de página, pestañas genéricas de taller (#extra-0)
    # y carruseles de productos relacionados para no contaminar el texto de la ficha.
    for tag in soup.select(
        "header, nav, footer, aside, script, style, noscript, "
        ".header, .footer, .menu, .megamenu, #header, #footer, #extra-0, "
        ".related-products, .product-accessories, .crossselling, .featured-products, "
        ".products-section, .block-categories"
    ):
        tag.decompose()

    contenedor_ficha = (
        soup.select_one("#main .product-container, .product-container, #product-details, main, article")
        or soup
    )
    texto_completo = contenedor_ficha.get_text(" ", strip=True)

    # --- Año ---
    if "ano" not in detalle:
        ano = _extraer_ano(texto_completo)
        if ano:
            detalle["ano"] = ano

    # --- Peso ---
    if "peso_kg" not in detalle:
        peso = _extraer_peso(texto_completo)
        if peso is not None:
            detalle["peso_kg"] = peso

    # --- Batería ---
    if "bateria_wh" not in detalle:
        bateria = _extraer_bateria(texto_completo)
        if bateria is not None:
            detalle["bateria_wh"] = bateria

    # --- Salud de Batería (SoH %) y Ciclos ---
    salud_pct, ciclos_bat = _extraer_salud_bateria(texto_completo)
    if salud_pct is not None:
        detalle["bateria_salud_pct"] = salud_pct
    if ciclos_bat is not None:
        detalle["bateria_ciclos"] = ciclos_bat

    # --- Disponibilidad (Reservada / Agotada) ---
    if not _extraer_disponibilidad_ficha(soup, texto_completo):
        detalle["disponible"] = False

    # --- Range Extender ---
    if "range_extender_wh" not in detalle:
        extender = _extraer_range_extender(texto_completo)
        if extender is not None:
            detalle["range_extender_wh"] = extender
            if "bateria_wh" in detalle and detalle["bateria_wh"] is not None:
                if detalle["bateria_wh"] <= 600:
                    detalle["bateria_wh"] += extender

    # --- Kilometraje ---
    if "km" not in detalle:
        km = _extraer_km(texto_completo)
        if km is not None:
            detalle["km"] = km
        elif not km_ya_conocido:
            # Fallback a visión por IA si los kilómetros no aparecen en string ni int en los datos
            km_foto = _extraer_km_de_imagenes(soup, url_ficha=url, img_urls=img_urls_galeria)
            detalle["km_vision_checked"] = True
            if km_foto is not None:
                detalle["km"] = km_foto

    # --- Motor ---
    if "motor" not in detalle:
        motor = _extraer_motor(texto_completo)
        if motor:
            detalle["motor"] = motor

    # --- Talla ---
    if "talla" not in detalle:
        talla = _extraer_talla(texto_completo)
        if talla:
            detalle["talla"] = talla

    # --- Suspensión trasera ---
    if "suspension_trasera" not in detalle:
        if "doble-suspension" in url.lower():
            detalle["suspension_trasera"] = "si"
        else:
            susp = _detectar_suspension_trasera(texto_completo)
            if susp is not None:
                detalle["suspension_trasera"] = "si" if susp else "no"

    # --- Material de cuadro ---
    if "cuadro_material" not in detalle:
        cuadro = _extraer_cuadro(texto_completo)
        if cuadro:
            detalle["cuadro_material"] = cuadro

    # --- Componentes ---
    if "componentes" not in detalle:
        componentes = _extraer_componentes(texto_completo)
        if componentes:
            detalle["componentes"] = componentes

    # --- Modalidad ---
    if "modalidad" not in detalle:
        modalidad = _extraer_modalidad(texto_completo)
        if modalidad:
            detalle["modalidad"] = modalidad

    # --- Recorrido de suspensión (mm) ---
    if "recorrido_mm" not in detalle:
        recorrido = _extraer_recorrido(texto_completo)
        if recorrido:
            detalle["recorrido_mm"] = recorrido

    # --- Guardar en caché para futuras consultas ---
    if detalle:
        _guardar_en_cache(url, detalle)

    return detalle


# ---------------------------------------------------------------------------
# 2. DuckDuckGo (fallback general)
# ---------------------------------------------------------------------------

def _buscar_duckduckgo(consulta: str) -> str:
    """Hace una búsqueda en DuckDuckGo HTML y devuelve el HTML de resultados."""
    import requests
    url = "https://html.duckduckgo.com/html/"
    try:
        resp = requests.post(url, data={"q": consulta}, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        }, timeout=20)
        if resp.status_code == 200:
            return resp.text
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Extractores de texto
# ---------------------------------------------------------------------------

def _extraer_ano(texto: str) -> Optional[int]:
    texto_norm = texto.replace("\u202f", " ")
    # 1. Priorizar etiquetas explícitas de año del modelo
    for m in re.finditer(
        r"\b(?:año(?:\s+del\s+modelo)?|ano|temporada)\s*[:\-]?\s*(20[12]\d)\b",
        texto_norm,
        re.IGNORECASE,
    ):
        ano = int(m.group(1))
        if 2015 <= ano <= 2030:
            return ano

    # 2. Fallback general ignorando fechas de entrega, compra/venta o copyright
    palabras_fecha = (
        "entrega", "estimada", "envío", "envio", "recíbela", "recibela",
        "vendida", "comprada", "copyright", "©",
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
        "ene.", "feb.", "mar.", "abr.", "may.", "jun.",
        "jul.", "ago.", "sep.", "oct.", "nov.", "dic.",
    )
    for match in re.finditer(r"\b(20[12]\d)\b", texto_norm):
        inicio = max(0, match.start() - 45)
        fin = min(len(texto_norm), match.end() + 25)
        contexto = f"{texto_norm[inicio:match.start()]} {texto_norm[match.end():fin]}".lower()
        if any(p in contexto for p in palabras_fecha):
            continue
        ano = int(match.group(1))
        if 2015 <= ano <= 2030:
            return ano
    return None


def _extraer_peso(texto: str) -> Optional[float]:
    texto_norm = texto.replace("\u202f", " ")
    # 1. Priorizar 'Peso: XX kg' directo sin 'embalaje' ni 'ciclista'/'máximo'
    for match in re.finditer(
        r"\bpeso(?:\s+aprox\.?|\s+aproximado)?\s*[:\-]?\s*(\d+(?:[.,]\d+)?)\s*kg\b",
        texto_norm,
        re.IGNORECASE,
    ):
        try:
            val = float(match.group(1).replace(",", "."))
            if 10.0 <= val <= 32.0:
                return val
        except ValueError:
            pass

    # 2. Fallback general ignorando peso con embalaje o peso máximo de ciclista
    for match in re.finditer(r"(\d+(?:[.,]\d+)?)\s*kg\b", texto_norm, re.IGNORECASE):
        inicio = max(0, match.start() - 45)
        contexto = texto_norm[inicio:match.start()].lower()
        if any(p in contexto for p in ("embalaje", "ciclista", "máximo", "maximo", "autorizado", "carga")):
            continue
        try:
            val = float(match.group(1).replace(",", "."))
            if 10.0 <= val <= 32.0:
                return val
        except ValueError:
            pass
    return None


def _extraer_bateria(texto: str) -> Optional[int]:
    if not texto:
        return None
    texto_norm = texto.replace("\u202f", " ").replace("\u00a0", " ")
    # 1. Si menciona la capacidad nominal original (ej. Upway: "capacidad original de 750 Wh, es decir, 670 Wh"),
    # usar la capacidad nominal del modelo y dejar la degradación en bateria_salud_pct.
    match_orig = re.search(
        r"(?:capacidad|valor)\s+original\s+de\s+(\d{3,4})\s*wh\b",
        texto_norm,
        re.IGNORECASE,
    )
    if match_orig:
        val_orig = int(match_orig.group(1))
        if 250 <= val_orig <= 1200:
            return val_orig

    # 2. Búsqueda de modelos conocidos de batería donde los Wh vienen en el nombre
    # (ej. Giant EnergyPak Smart 625, Bosch PowerTube 750, Yamaha InTube 630)
    patrones_modelo = (
        r"EnergyPak\s*(?:Smart\s*)?(\d{3,4})",
        r"PowerTube\s*(\d{3,4})",
        r"PowerPack\s*(\d{3,4})",
        r"InTube\s*(\d{3,4})",
        r"Simplo\s*(\d{3,4})",
        r"Darfon\s*(\d{3,4})",
        r"Flyer\s*(?:FIB\s*)?(\d{3,4})",
    )
    for p_mod in patrones_modelo:
        m_mod = re.search(p_mod, texto_norm, re.IGNORECASE)
        if m_mod:
            try:
                val_mod = int(m_mod.group(1))
                if 250 <= val_mod <= 1200:
                    return val_mod
            except ValueError:
                pass

    # 3. Búsqueda general de Wh ignorando menciones de Range Extender compatible/opcional
    palabras_extender_opcional = (
        "range extender compatible", "compatible con extender", "extender compatible",
        "extender opcional", "opción de extender", "opcion de extender",
        "compatible con batería externa", "compatible con bateria externa",
        "se vende por separado", "se adquiere por separado", "no incluido", "no incluida"
    )
    for match in re.finditer(r"(\d+)\s*wh\b", texto_norm, re.IGNORECASE):
        ini = max(0, match.start() - 50)
        fin = min(len(texto_norm), match.end() + 50)
        ctx = texto_norm[ini:fin].lower()
        if any(exc in ctx for exc in palabras_extender_opcional):
            continue
        try:
            val = int(match.group(1))
            if 250 <= val <= 1200:
                return val
        except ValueError:
            pass
    return None


def _extraer_salud_bateria(texto: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Extrae el estado de salud real de la batería (SoH en %, ej. 90% en Upway o Bike Ocasión)
    y el número de ciclos de carga diagnosticados cuando están presentes en la ficha.
    Devuelve (salud_pct, ciclos).
    """
    if not texto:
        return None, None

    texto_norm = texto.replace("\u202f", " ").replace("\u00a0", " ")
    salud_pct: Optional[int] = None
    ciclos: Optional[int] = None

    patrones_salud = (
        r"estado\s+de\s+salud\s*[:\-]?\s*(\d{2,3})\s*%",
        r"conserva\s+el\s+(\d{2,3})\s*%\s+de\s+(?:su\s+)?capacidad",
        r"capacidad\s+(?:restante|real|comprobada|residual|actual)\s*(?:es\s+del\s*|:\s*|\-\s*)?(\d{2,3})\s*%",
        r"(?:salud|estado|rendimiento|vida\s+[úu]til|condici[óo]n)\s+(?:de\s+(?:la\s+)?)?bater[ií]a\s*[:\-]?\s*(\d{2,3})\s*%",
        r"bater[ií]a\s+(?:al|con(?:\s+el)?)\s*(\d{2,3})\s*%\s*(?:de\s+capacidad|de\s+salud)?",
        r"diagn[óo]stico\s+(?:de\s+)?bater[ií]a\s*[:\-]?\s*(\d{2,3})\s*%",
        r"test\s+(?:de\s+)?bater[ií]a\s*[:\-]?\s*(\d{2,3})\s*%",
        r"%\s*bater[ií]a\s*[:\-]?\s*(\d{2,3})\s*%?",
        r"\bsoh\s*[:\-]?\s*(\d{2,3})\s*%",
    )
    for patron in patrones_salud:
        m = re.search(patron, texto_norm, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            if 40 <= val <= 100:
                salud_pct = val
                break

    # Si dice explícitamente "batería nueva", "batería sustituida", "batería reemplazada",
    # "batería a estrenar" o en Upway "Batería Estado: Nueva" / "Batería Estado: Reemplazada"
    if salud_pct is None:
        if re.search(
            r"bater[ií]a\s+(?:estado\s*:\s*)?(?:nueva|reemplazada|sustituida|a\s+estrenar)\b|"
            r"(?:bater[ií]a\s+de\s+reemplazo|bater[ií]a\s+sin\s+usar)\b",
            texto_norm,
            re.IGNORECASE,
        ):
            salud_pct = 100
            if ciclos is None:
                ciclos = 0

    patrones_ciclos = (
        r"(?:n[úu]mero|n[ºo]|n\.º)\s+de\s+ciclos(?:\s+de\s+carga)?(?:\s+de\s+la\s+bater[ií]a)?\s*[:\-]?\s*(\d{1,4})\b",
        r"ciclos\s+de\s+carga(?:\s+de\s+la\s+bater[ií]a)?\s*[:\-]?\s*(\d{1,4})\b",
        r"\b(\d{1,4})\s+ciclos\s+de\s+carga\b",
        r"(?:ciclos|recargas|cargas)\s+(?:de\s+)?bater[ií]a\s*[:\-]?\s*(\d{1,4})\b",
        r"bater[ií]a\s*[:\-]?\s*.*?(\d{1,4})\s+ciclos\b",
        r"\b(\d{1,4})\s+ciclos\b",
    )
    for patron in patrones_ciclos:
        m = re.search(patron, texto_norm, re.IGNORECASE)
        if m:
            val_c = int(m.group(1))
            if 0 <= val_c <= 3000:
                ciclos = val_c
                break

    return salud_pct, ciclos


def _extraer_disponibilidad_ficha(soup: BeautifulSoup, texto_completo: str) -> bool:
    """
    Verifica en la ficha de detalle si la bicicleta sigue disponible para compra
    o si está marcada como Reservada, Agotada o Fuera de stock.
    """
    if soup is not None:
        badge_no_disp = soup.select_one(
            ".product-unavailable, .out-of-stock, .out_of_stock, .sold-out, "
            ".agotado, .reservado, #product-availability .product-unavailable"
        )
        if badge_no_disp is not None:
            return False

        avail_el = soup.select_one("#product-availability, .product-availability, .availability-label")
        if avail_el:
            txt_avail = avail_el.get_text(" ", strip=True)
            if re.search(
                r"\b(?:reservad[oa]s?|agotad[oa]s?|vendid[oa]s?|sin\s+stock|no\s+disponible|fuera\s+de\s+stock)\b",
                txt_avail,
                re.IGNORECASE,
            ):
                return False

    if texto_completo:
        if re.search(
            r"\b(?:bicicleta\s+reservada|producto\s+agotado|fuera\s+de\s+stock| temporalmente\s+sin\s+stock)\b",
            texto_completo,
            re.IGNORECASE,
        ):
            return False

    return True


def _extraer_range_extender(texto: str) -> Optional[int]:
    """
    Detecta si una bicicleta incluye un Range Extender o segunda batería externa.
    Distingue inclusión real ("+ extender", "incluye batería externa 252wh", "con range extender")
    frente a mera compatibilidad de catálogo ("compatible con extender", "opcional", "no incluido").

    Devuelve la capacidad en Wh del extender (int) o None si no incluye.
    """
    if not texto:
        return None

    texto_norm = texto.replace("\u202f", " ")
    texto_lower = texto_norm.lower()

    terminos_extender = (
        "extender", "range extender", "batería externa", "bateria externa",
        "batería adicional", "bateria adicional", "batería suplementaria", "bateria suplementaria",
        "segunda batería", "segunda bateria", "2 baterías", "2 baterias",
        "batería extra", "bateria extra", "xpro", "x-pro", "powermore",
    )
    if not any(t in texto_lower for t in terminos_extender):
        return None

    palabras_exclusion = (
        "compatible con", "compatibilidad con", "opcional", "opción de", "opcion de",
        "posibilidad de", "admite", "preparado para", "preparada para",
        "no incluye", "no incluido", "no incluida", "se vende por separado",
        "se adquiere por separado", "sin extender", "sin batería adicional",
    )

    termino_bateria = (
        r"(?:range\s*extender|extender|"
        r"bater[ií]a\s+(?:externa|adicional|extra|suplementaria|secundaria)|"
        r"(?:segunda|2ª|2a)\s+bater[ií]a|"
        r"x-?pro|powermore)"
    )

    # 1. Patrón con Wh explícito (ej. "+ Batería XPro 180Wh", "incluye range extender de 252Wh")
    patron_con_wh = re.finditer(
        rf"(?:(?:\+|con|incluye|incluido|incluida|regalo|segunda|extra|pack)\s+[^.]{{0,40}}?"
        rf"{termino_bateria}"
        rf"[^.]{{0,30}}?(\d{{3}})\s*wh\b)"
        rf"|"
        rf"(?:(\d{{3}})\s*wh\b[^.]{{0,30}}?"
        rf"{termino_bateria}"
        rf"[^.]{{0,40}}?(?:incluid[oa]|de\s+regalo|\+))",
        texto_norm,
        re.IGNORECASE,
    )

    for m in patron_con_wh:
        fragmento = m.group(0).lower()
        if any(exc in fragmento for exc in palabras_exclusion):
            continue
        match_wh = re.search(r"(\d{3})\s*wh", fragmento)
        if match_wh:
            val = int(match_wh.group(1))
            if 140 <= val <= 380:
                return val

    # 2. Patrón de inclusión nominal sin Wh explícito -> inferir por marca/modelo
    patrones_inclusion = (
        r"\+\s*(?:range\s*extender|extender|bater[ií]a\s+externa|x-?pro|powermore)\b",
        r"\bincluye\s+(?:range\s*extender|extender|bater[ií]a\s+externa|segunda\s+bater[ií]a|x-?pro|powermore)\b",
        r"\bcon\s+(?:range\s*extender|extender|bater[ií]a\s+externa|bater[ií]a\s+adicional|x-?pro|powermore)\b",
        r"\b(?:range\s*extender|extender|bater[ií]a\s+externa|x-?pro|powermore)\s+incluid[oa]\b",
        r"\b(?:2|dos)\s+bater[ií]as\s+incluidas\b",
    )

    for patron in patrones_inclusion:
        for m in re.finditer(patron, texto_norm, re.IGNORECASE):
            inicio = max(0, m.start() - 50)
            fin = min(len(texto_norm), m.end() + 50)
            contexto = texto_norm[inicio:fin].lower()
            if any(exc in contexto for exc in palabras_exclusion):
                continue

            if any(k in texto_lower for k in ("orbea", "rise")):
                return 252
            if any(k in texto_lower for k in ("bh", "ilynx", "atomx", "xpro", "x-pro")):
                return 180
            if any(k in texto_lower for k in ("specialized", "levo sl", "kenevo sl")):
                return 160
            if any(k in texto_lower for k in ("trek", "fuel exe", "scott lumen", "tq")):
                return 160
            if "powermore" in texto_lower:
                return 250
            if any(k in texto_lower for k in ("fazua", "ride 60")):
                return 210
            return 250

    return None



def _normalizar_km_existente(valor: Any) -> Optional[int]:
    """
    Normaliza un valor de kilómetros si ya viene como int, float o string numérico/etiquetado.
    Devuelve int si es válido (0 <= km <= 99999) o None si no existe/no es válido.
    """
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        val_int = int(round(float(valor)))
        return val_int if 0 <= val_int <= 99999 else None
    if isinstance(valor, str):
        limpio = valor.strip()
        if not limpio or limpio in ("-", "null", "none", "n/a"):
            return None
        if re.fullmatch(r"\d[\d.,]*", limpio):
            try:
                val_int = int(limpio.replace(".", "").replace(",", ""))
                return val_int if 0 <= val_int <= 99999 else None
            except ValueError:
                pass
        return _extraer_km(limpio)
    return None


def _descargar_bytes_imagen(img_url: str) -> Optional[bytes]:
    """Descarga los bytes de una imagen de galería usando cabeceras de navegador real."""
    headers = {
        "User-Agent": cfg.USER_AGENTS[0] if getattr(cfg, "USER_AGENTS", None) else "Mozilla/5.0",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    try:
        r = requests.get(img_url, headers=headers, timeout=10)
        if r.status_code == 200 and len(r.content) >= 2500:
            return r.content
    except Exception:
        pass

    if SCRAPLING_AVAILABLE:
        try:
            rotator = crear_proxy_rotator()
            kwargs_img = {"impersonate": "chrome120", "timeout": 12}
            if rotator is not None:
                kwargs_img["proxy_rotator"] = rotator
            page = Fetcher.get(img_url, **kwargs_img)
            body = getattr(page, "body", None)
            if page.status == 200 and body and len(body) >= 2500:
                return bytes(body)
        except Exception:
            pass
    return None


def _parsear_respuesta_km_vision(texto_json: str) -> Optional[int]:
    """Extrae el entero de kilómetros del JSON devuelto por Gemini Vision."""
    if not texto_json:
        return None
    limpio = texto_json.replace("```json", "").replace("```", "").strip()
    match = re.search(r"\{.*\}", limpio, re.DOTALL)
    if match:
        limpio = match.group(0)
    try:
        parsed = json.loads(limpio)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None

    for key in ("km", "odometer_total_km", "total_km", "kilometros", "odometro"):
        km_val = parsed.get(key)
        if km_val is not None and not isinstance(km_val, bool):
            if isinstance(km_val, (int, float)) and 0 < km_val <= 99999:
                return int(round(float(km_val)))
            if isinstance(km_val, str):
                norm = _normalizar_km_existente(km_val)
                if norm is not None and norm > 0:
                    return norm
    return None


def _extraer_km_de_imagenes(
    soup: Optional[BeautifulSoup] = None,
    url_ficha: str = "",
    img_urls: Optional[List[str]] = None,
) -> Optional[int]:
    """
    Si la tienda no incluye el kilometraje en la ficha de texto ni en el SKU,
    pero incluye fotografías del cuentakilómetros/odómetro del display en la galería
    (caso habitual en Buhobike segunda mano), inspecciona las imágenes de la galería
    con Gemini Flash Vision para extraer el valor exacto de km.
    """
    if not cfg.GEMINI_API_KEY:
        return None

    candidatas = list(img_urls) if img_urls else _recolectar_urls_imagenes_ficha(soup, url_ficha=url_ficha)
    if not candidatas:
        return None

    candidatas = candidatas[:6]
    imagenes_b64: List[Tuple[str, str]] = []
    for img_url in candidatas:
        raw_bytes = _descargar_bytes_imagen(img_url)
        if raw_bytes:
            b64 = base64.b64encode(raw_bytes).decode("utf-8")
            mime = "image/webp" if img_url.lower().endswith(".webp") else (
                "image/png" if img_url.lower().endswith(".png") else "image/jpeg"
            )
            imagenes_b64.append((img_url, mime, b64))

    if not imagenes_b64:
        return None

    prompt = (
        'Analiza estas imágenes de la galería de una bicicleta eléctrica o su display. '
        'Si en alguna imagen ves una pantalla, display o ciclocomputador mostrando el odómetro '
        'o kilometraje total acumulado (ODO / km / dst), devuelve el número entero de kilómetros '
        'en formato JSON: {"km": 1234}. '
        'Si en ninguna imagen se ve el kilometraje acumulado en pantalla, devuelve estrictamente {"km": null}.'
    )

    modelos_vision = ["gemini-3.5-flash-lite"]
    for m in getattr(cfg, "GEMINI_MODELS", []):
        if m not in modelos_vision:
            modelos_vision.append(m)

    parts: List[dict] = [{"text": prompt}]
    for _, mime, b64 in imagenes_b64:
        parts.append({"inline_data": {"mime_type": mime, "data": b64}})

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.0,
            "responseMimeType": "application/json",
        },
    }

    for model in modelos_vision:
        url_api = f"{cfg.GEMINI_API_URL.format(model=model)}?key={cfg.GEMINI_API_KEY}"
        try:
            res = requests.post(url_api, json=payload, timeout=20)
            if res.status_code != 200:
                log.debug(f"[Visión IA {model}] HTTP {res.status_code}: {res.text[:160]}")
                continue
            data = res.json()
            res_parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            txt = "".join(p.get("text", "") for p in res_parts if "text" in p)
            km_detectado = _parsear_respuesta_km_vision(txt)
            if km_detectado is not None:
                log.info(
                    f"[Visión IA {model}] Odómetro detectado en galería ({len(imagenes_b64)} fotos): {km_detectado} km"
                )
                return km_detectado
            # Si el modelo respondió válidamente {"km": null}, no hay odómetro en las fotos
            if '"km": null' in txt.lower() or '"km":null' in txt.lower():
                return None
        except Exception as e:
            log.debug(f"[Visión IA {model}] Excepción analizando galería: {e}")
            continue

    return None


def _extraer_km(texto: str) -> Optional[int]:
    texto_norm = texto.replace("\u202f", " ")

    # 1. Patrones con '< 5 km' o '< 10 km' (típicos de Upway o filtros de reestreno)
    match_menor = re.search(r"<\s*(\d+)\s*km\b", texto_norm, re.IGNORECASE)
    if match_menor:
        return int(match_menor.group(1))

    # 2. Patrones con etiqueta explícita de odómetro / kilometraje del vehículo
    # Ej: "Kilometraje: 1.250 km", "Odómetro: 3400 km", "Kilómetros: 800", "Km: 1.837"
    for match_etiqueta in re.finditer(
        r"\b(?:(?:kilometraje|kilómetros|kilometros|odómetro|odometro|recorrido|rodaje)\s*[:\-]?\s*(\d[\d.,]*)|kms?\s*[:\-]\s*(\d[\d.,]*))\s*(?:km\b)?",
        texto_norm,
        re.IGNORECASE,
    ):
        try:
            raw_num = match_etiqueta.group(1) or match_etiqueta.group(2)
            km_str = raw_num.replace(".", "").replace(",", "")
            val = int(km_str)
            if 0 <= val <= 99999:
                return val
        except ValueError:
            pass

    # 3. Fallback general: buscar 'XXXX km', descartando estrictamente falsos positivos de contexto:
    # - Mantenimiento de cadena / engrase (ej. 'hacerle unos 700 km sin otra necesidad de engrasar la cadena')
    # - Intervalos de cambio de componentes (ej. 'cambies la cadena (entre 700 y 1500 km después de la compra)')
    # - Autonomía de la batería ('autonomía de hasta 100 km')
    # - Radio / distancia geográfica ('a 50 km de Madrid')
    for match in re.finditer(r"(\d[\d.,]*)\s*km\b", texto_norm, re.IGNORECASE):
        inicio = max(0, match.start() - 65)
        fin = min(len(texto_norm), match.end() + 65)
        contexto_previo = texto_norm[inicio:match.start()].lower()
        contexto_posterior = texto_norm[match.end():fin].lower()
        contexto_total = f"{contexto_previo} {contexto_posterior}"

        palabras_bloqueadas = (
            "engrasar", "engrase", "cera", "cadena", "mantenimiento",
            "cambies la cadena", "cambiar la cadena", "después de la compra",
            "tras la compra", "autonomía", "autonomia", "alcance",
            "radio", "distancia", "radio de", "a menos de", "garantía de",
        )
        if any(p in contexto_total for p in palabras_bloqueadas):
            continue

        try:
            km_str = match.group(1).replace(".", "").replace(",", "")
            val = int(km_str)
            if 0 <= val <= 99999:
                return val
        except ValueError:
            pass

    return None


def _extraer_motor(texto: str) -> Optional[str]:
    texto_lower = texto.lower()
    patrones_motor = [
        (r"\bshimano\b.{0,25}?\bep801\b", "Shimano EP801"),
        (r"\bshimano\b.{0,25}?\bep8(?:00)?[\-\s]*rs\b", "Shimano EP8 RS"),
        (r"\bshimano\b.{0,25}?\bep8(?:00)?\b", "Shimano EP8"),
        (r"\bshimano\b.{0,25}?\bep6(?:00)?\b", "Shimano EP6"),
        (r"\bbosch\b.{0,30}?\bperformance\s+line\s+sx\b|\bbosch\s+sx\b", "Bosch Performance Line SX"),
        (r"\bbosch\b.{0,30}?\bperformance\s+line\s+cx\b|\bbosch\s+cx\b", "Bosch Performance Line CX"),
        (r"\bbosch\b.{0,30}?\bperformance\s+line\b", "Bosch Performance Line"),
        (r"\bbh\s*2exmag\b|\b2exmag\b|\bbh\s*2e\b", "BH 2EXMAG"),
        (r"\bfazua\b.{0,25}?\bride\s*60\b", "Fazua Ride 60"),
        (r"\bfazua\b", "Fazua"),
        (r"\btq\b.{0,25}?\bhpr\s*\d*\b|\bmotor\s+tq\b", "TQ HPR50"),
        (r"\bmahle\b", "Mahle"),
        (r"\bspecialized\b.{0,20}?\bsl\b", "Specialized SL"),
        (r"\bbrose\b", "Brose"),
        (r"\byamaha\b.{0,25}?\bpw[\-\s]*x3\b", "Yamaha PW-X3"),
        (r"\byamaha\b", "Yamaha"),
        (r"\bgiant\b.{0,20}?\bsyncdrive\b|\bsyncdrive\b", "Giant SyncDrive"),
    ]
    for patron, nombre in patrones_motor:
        if re.search(patron, texto_lower):
            return nombre
    return None


def _extraer_talla(texto: str) -> Optional[str]:
    match = re.search(r"\btalla\s*:\s*([A-Za-z]+)\b", texto, re.IGNORECASE)
    if match:
        t = match.group(1).upper()
        if t in ("XS", "S", "M", "L", "XL", "XXL", "SM", "ML"):
            return t
    # Buscar patrones como "Talla M" o "T-M"
    match2 = re.search(r"\b(?:Talla|T)[\s\-]+(XS|S|M|L|XL|SM|ML)\b", texto, re.IGNORECASE)
    if match2:
        return match2.group(1).upper()
    return None


def _detectar_suspension_trasera(texto: str) -> Optional[bool]:
    texto_lower = texto.lower()
    negativos = [
        "no tiene suspensión trasera", "sin amortiguador", "solo horquilla",
        "hardtail", "semirrígida", "semirrigida", "sin suspensión trasera", "no amortiguador",
    ]
    if any(k in texto_lower for k in negativos):
        return False
    positivos = [
        "amortiguador", "suspensión trasera", "doble suspensión", "doble suspension",
        "full suspension", "full-suspension", "suspension trasera",
    ]
    if any(k in texto_lower for k in positivos):
        return True
    return None


def _extraer_cuadro(texto: str) -> Optional[str]:
    texto_lower = texto.lower()
    if re.search(r"\b(carbono|carbon|fibra de carbono)\b", texto_lower):
        return "Carbono"
    if re.search(r"\b(aluminio|aluminium|aluminum|alloy)\b", texto_lower):
        return "Aluminio"
    return None


def _extraer_componentes(texto: str) -> Optional[str]:
    texto_lower = texto.lower()
    partes = []
    if re.search(r"\b(xt|xtr|axs|x01|xx1|gx\s+eagle)\b", texto_lower):
        partes.append("XT/AXS")
    elif re.search(r"\bshimano\s+slx\b|\bslx\b", texto_lower):
        partes.append("Shimano SLX")
    elif re.search(r"\bshimano\s+deore\b", texto_lower):
        partes.append("Shimano Deore")
    elif re.search(r"\bsram\s+gx\b", texto_lower):
        partes.append("SRAM GX")

    if re.search(r"\b(kashima|ultimate|factory)\b", texto_lower):
        partes.append("Suspensión premium")
    elif re.search(r"\bfox\s+(?:34|36|38|float)\b", texto_lower):
        partes.append("Fox Float")
    elif re.search(r"\bmarzocchi\s+bomber\b", texto_lower):
        partes.append("Marzocchi Bomber")
    elif re.search(r"\brock\s*shox\s+(?:sid|pike|lyrik|revelation|deluxe)\b", texto_lower):
        partes.append("RockShox")

    if partes:
        return "; ".join(partes)
    return None


def _extraer_recorrido(texto: str) -> Optional[int]:
    """
    Extrae el recorrido de suspensión en mm (ej. 100, 120, 130, 140, 150, 160 mm).
    Prioriza etiquetas explícitas de recorrido/travel o suspensiones reconocidas.
    Rango válido e-MTB: 100 <= mm <= 180.
    """
    texto_norm = texto.replace("\u202f", " ")

    # 1. Patrones explícitos con etiqueta de recorrido / travel
    patrones_etiqueta = [
        r"\b(?:recorrido(?:\s+(?:de\s+)?suspensi[oó]n|\s+horquilla|\s+delantero|\s+trasero)?|travel)\s*[:\-]?\s*(\d{2,3})\s*mm\b",
        r"\b(\d{2,3})\s*mm\s*(?:de\s+)?(?:recorrido|travel)\b",
        r"\b(\d{2,3})\s*/\s*\d{2,3}\s*mm\b",
    ]
    for p in patrones_etiqueta:
        m = re.search(p, texto_norm, re.IGNORECASE)
        if m:
            try:
                val = int(m.group(1))
                if 100 <= val <= 180:
                    return val
            except ValueError:
                pass

    # 2. Patrones con marcas/modelos de suspensión y recorrido
    m_susp = re.search(
        r"\b(?:fox\s*(?:32|34|36|38|float)?|rock\s*shox\s*(?:sid|pike|lyrik|revelation|yari|deluxe)?|marzocchi|ohlins)\b.{0,25}?\b(\d{2,3})\s*mm\b",
        texto_norm,
        re.IGNORECASE,
    )
    if m_susp:
        try:
            val = int(m_susp.group(1))
            if 100 <= val <= 180:
                return val
        except ValueError:
            pass

    return None


def _extraer_modalidad(texto: str) -> Optional[str]:
    texto_lower = texto.lower()
    patrones_modalidad = [
        (r"\bdowncountry\b", "Downcountry"),
        (r"\blight\s+e-?mtb\b", "Light e-MTB"),
        (r"\bcross\s+country\b|\bxc\b", "XC"),
        (r"\ball\s+mountain\b", "All Mountain"),
        (r"\benduro\b", "Enduro"),
        (r"\btrail\b", "Trail"),
    ]
    for patron, nombre in patrones_modalidad:
        if re.search(patron, texto_lower):
            return nombre
    return None


# ---------------------------------------------------------------------------
# API principal
# ---------------------------------------------------------------------------

def enriquecer_bici(bici: Bicicleta, url_ficha: Optional[str] = None) -> Bicicleta:
    """
    Intenta completar datos faltantes de una bici.

    Orden:
      1. Ficha del producto del propio sitio (Scrapling) - si se pasa url_ficha.
      2. DuckDuckGo HTML - fallback general.

    Solo busca los campos que faltan: peso_kg, suspension_trasera, ano, km,
    talla, bateria_wh, motor, cuadro_material, componentes, modalidad, recorrido_mm.

    Devuelve la bici con los campos que se lograron completar.
    """
    bici.km = _normalizar_km_existente(bici.km)

    faltan = (
        bici.peso_kg is None or bici.suspension_trasera is None or bici.ano is None
        or bici.km is None or bici.talla is None or bici.bateria_wh is None
        or bici.motor is None or bici.cuadro_material is None
        or bici.componentes is None or bici.modalidad is None
        or bici.recorrido_mm is None
    )

    if not faltan:
        return bici

    # Paso 1: ficha del propio sitio (mas fiable)
    if url_ficha and SCRAPLING_AVAILABLE:
        try:
            detalle = _extraer_desde_ficha_sitio(
                url_ficha,
                bici.sitio,
                km_ya_conocido=(bici.km is not None),
            )
            if detalle:
                bici = _aplicar_detalle(bici, detalle)
                log.info(
                    f"[Enriquecedor] {bici.titulo} completado desde ficha del sitio: "
                    f"{list(detalle.keys())}"
                )
        except Exception as e:
            log.warning(f"[Enriquecedor] Ficha del sitio fallo para {bici.titulo}: {e}")

    # Si faltan campos críticos, intentar DuckDuckGo como fallback
    faltan_criticos = (
        bici.peso_kg is None or bici.suspension_trasera is None or bici.ano is None
    )
    if faltan_criticos:
        try:
            consulta = f"{bici.sitio} {bici.titulo} especificaciones peso kg año"
            html = _buscar_duckduckgo(consulta)
            if html:
                soup = BeautifulSoup(html, "html.parser")
                fragmentos = []
                for res in soup.select(".result")[:5]:
                    titulo_el = res.select_one(".result__a")
                    snippet_el = res.select_one(".result__snippet")
                    texto = ""
                    if titulo_el:
                        texto += titulo_el.get_text(" ", strip=True) + " "
                    if snippet_el:
                        texto += snippet_el.get_text(" ", strip=True) + " "
                    fragmentos.append(texto)

                texto_completo = " ".join(fragmentos)
                if texto_completo:
                    detalle = {}
                    if bici.peso_kg is None:
                        peso = _extraer_peso(texto_completo)
                        if peso is not None:
                            detalle["peso_kg"] = peso
                    if bici.ano is None:
                        ano = _extraer_ano(texto_completo)
                        if ano is not None:
                            detalle["ano"] = ano
                    if bici.suspension_trasera is None:
                        susp = _detectar_suspension_trasera(texto_completo)
                        if susp is not None:
                            detalle["suspension_trasera"] = "si" if susp else "no"

                    if detalle:
                        bici = _aplicar_detalle(bici, detalle)
                        log.info(
                            f"[Enriquecedor] {bici.titulo} completado desde DuckDuckGo: "
                            f"{list(detalle.keys())}"
                        )
        except Exception as e:
            log.warning(f"[Enriquecedor] DuckDuckGo fallo para {bici.titulo}: {e}")

    return bici


def _aplicar_detalle(bici: Bicicleta, detalle: dict) -> Bicicleta:
    """Aplica los campos del detalle a la bici solo si faltan o actualiza el total con range extender."""
    if detalle.get("disponible") is False:
        bici.disponible = False

    extender = detalle.get("range_extender_wh")
    if extender is not None and bici.range_extender_wh is None:
        bici.range_extender_wh = extender
        if bici.bateria_wh is not None:
            if "bateria_wh" in detalle and detalle["bateria_wh"] > bici.bateria_wh:
                bici.bateria_wh = detalle["bateria_wh"]
            elif bici.bateria_wh <= 600:
                bici.bateria_wh += extender

    for campo, valor in detalle.items():
        if campo in ("range_extender_wh", "bateria_wh", "disponible", "km_vision_checked"):
            continue
        if valor is not None and getattr(bici, campo, None) is None:
            setattr(bici, campo, valor)

    if "bateria_wh" in detalle and detalle["bateria_wh"] is not None and bici.bateria_wh is None:
        bici.bateria_wh = detalle["bateria_wh"]

    # Bicicleta nueva a estrenar con garantía oficial (ej. Mammoth Bikes km=0, garantia_anos >= 2)
    if getattr(bici, "km", None) == 0 and (getattr(bici, "garantia_anos", 0) or 0) >= 2:
        if getattr(bici, "bateria_salud_pct", None) is None:
            bici.bateria_salud_pct = 100
        if getattr(bici, "bateria_ciclos", None) is None:
            bici.bateria_ciclos = 0

    return bici
