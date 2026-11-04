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
from typing import Optional, Dict
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


# ---------------------------------------------------------------------------
# Caché de fichas de detalle (tarea 12, Fase D)
# ---------------------------------------------------------------------------
CACHE_DIR = cfg.BASE_DIR / "cache"
CACHE_FILE = CACHE_DIR / "fichas_detalle.json"


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
    """Busca los datos extraídos de una ficha en el caché."""
    cache = _cargar_cache()
    return cache.get(url)


def _guardar_en_cache(url: str, datos: dict) -> None:
    """Guarda los datos extraídos de una ficha en el caché."""
    cache = _cargar_cache()
    cache[url] = datos
    _guardar_cache(cache)


# ---------------------------------------------------------------------------
# 1. Enriquecimiento desde la ficha del propio sitio (Scrapling)
# ---------------------------------------------------------------------------

def _extraer_desde_ficha_sitio(url: str, sitio_nombre: str) -> dict:
    """
    Entra a la ficha de producto del sitio y extrae los campos que pueda:
    talla, bateria_wh, km, motor, cuadro_material, ano, peso_kg,
    suspension_trasera, componentes, modalidad.
    Devuelve un dict con los campos encontrados (puede estar parcialmente vacio).
    """
    detalle: dict = {}
    if not SCRAPLING_AVAILABLE:
        return detalle

    # --- Caché: verificar si ya consultamos esta ficha antes ---
    cache_hit = _buscar_en_cache(url)
    if cache_hit:
        log.info(f"[Caché] Ficha ya consultada: {url} -> {list(cache_hit.keys())}")
        return dict(cache_hit)

    try:
        es_buhobike = "buhobike.com" in url.lower() or sitio_nombre.lower() == "buhobike"
        if es_buhobike:
            page = StealthyFetcher.fetch(
                url, headless=True, solve_cloudflare=True, timeout=60
            )
        else:
            page = Fetcher.get(url, impersonate="chrome120", timeout=30)
            if page.status != 200:
                # Fallback a stealth si el sitio tiene Cloudflare
                page = StealthyFetcher.fetch(
                    url, headless=True, solve_cloudflare=True, timeout=60
                )
        if page.status != 200:
            log.warning(f"[Enriquecedor] No se pudo abrir ficha {url} (status {page.status})")
            return detalle
    except Exception as e:
        log.warning(f"[Enriquecedor] Error abriendo ficha {url}: {e}")
        return detalle

    html = str(page.html_content)
    soup = BeautifulSoup(html, "html.parser")

    # 1. Extraer pares <dt>/<dd> estructurados si existen (Upway / PrestaShop data-sheet)
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if not dd:
            continue
        label = dt.get_text(" ", strip=True).lower()
        val = dd.get_text(" ", strip=True)
        if not val:
            continue
        if label in ("año", "ano", "año del modelo") and "ano" not in detalle:
            ano_dt = _extraer_ano(val)
            if ano_dt:
                detalle["ano"] = ano_dt
        elif "peso" in label and "peso_kg" not in detalle:
            peso_dt = _extraer_peso(val)
            if peso_dt is not None:
                detalle["peso_kg"] = peso_dt
        elif ("batería" in label or "bateria" in label) and "bateria_wh" not in detalle:
            bat_dt = _extraer_bateria(val)
            if bat_dt is not None:
                detalle["bateria_wh"] = bat_dt
        elif "talla" in label and "talla" not in detalle:
            talla_limpia = val.split(":")[0].strip() if ":" in val else val.split()[0].strip()
            if talla_limpia in ("XS", "S", "M", "L", "XL", "XXL"):
                detalle["talla"] = talla_limpia
        elif "motor" in label and "motor" not in detalle:
            detalle["motor"] = val
        elif ("cuadro" in label or "material" in label) and "cuadro_material" not in detalle:
            cuadro_dt = _extraer_cuadro(val)
            if cuadro_dt:
                detalle["cuadro_material"] = cuadro_dt
        elif ("suspensión" in label or "suspension" in label or "amortiguador" in label):
            if "semi" in val.lower() or "rígida" in val.lower() or "hardtail" in val.lower():
                detalle["suspension_trasera"] = "no"
            elif any(k in val.lower() for k in ["doble", "total", "completa", "full", "mm", "fox", "rockshox"]):
                detalle["suspension_trasera"] = "si"

    # 2. Eliminar menús, cabeceras, pies de página y carruseles de productos relacionados
    # para que el texto de la ficha no se contamine con otras bicicletas o el menú del sitio.
    for tag in soup.select(
        "header, nav, footer, aside, script, style, noscript, "
        ".header, .footer, .menu, .megamenu, #header, #footer, "
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

    # --- Kilometraje ---
    if "km" not in detalle:
        km = _extraer_km(texto_completo)
        if km is not None:
            detalle["km"] = km

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
    match = re.search(r"\b(20\d{2})\b", texto)
    if match:
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
    for match in re.finditer(r"(\d+)\s*wh\b", texto.replace("\u202f", " "), re.IGNORECASE):
        try:
            val = int(match.group(1))
            if 250 <= val <= 1200:
                return val
        except ValueError:
            pass
    return None


def _extraer_km(texto: str) -> Optional[int]:
    texto_norm = texto.replace("\u202f", " ")
    match_menor = re.search(r"<\s*(\d+)\s*km\b", texto_norm, re.IGNORECASE)
    if match_menor:
        return int(match_menor.group(1))
    match = re.search(r"(\d[\d.,]*)\s*km\b", texto_norm, re.IGNORECASE)
    if match:
        try:
            km_str = match.group(1).replace(".", "").replace(",", "")
            return int(km_str)
        except ValueError:
            pass
    return None


def _extraer_motor(texto: str) -> Optional[str]:
    texto_lower = texto.lower()
    patrones_motor = [
        (r"\bshimano\s+ep801\b", "Shimano EP801"),
        (r"\bshimano\s+ep8[\-\s]*rs\b", "Shimano EP8 RS"),
        (r"\bshimano\s+ep8\b", "Shimano EP8"),
        (r"\bshimano\s+ep6\b", "Shimano EP6"),
        (r"\bbosch\s+performance\s+line\s+sx\b|\bbosch\s+sx\b", "Bosch Performance Line SX"),
        (r"\bbosch\s+performance\s+line\s+cx\b|\bbosch\s+cx\b", "Bosch Performance Line CX"),
        (r"\bbosch\s+performance\s+line\b", "Bosch Performance Line"),
        (r"\bbh\s*2exmag\b|\b2exmag\b|\bbh\s*2e\b", "BH 2EXMAG"),
        (r"\bfazua\b", "Fazua"),
        (r"\btq\s*hpr\d*\b|\bmotor\s+tq\b", "TQ HPR50"),
        (r"\bmahle\b", "Mahle"),
        (r"\bspecialized\s+sl\b", "Specialized SL"),
        (r"\bbrose\b", "Brose"),
        (r"\byamaha\b", "Yamaha"),
        (r"\bgiant\s+syncdrive\b", "Giant SyncDrive"),
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
    if re.search(r"\b(kashima|ultimate|factory)\b", texto_lower):
        partes.append("Suspensión premium")
    if partes:
        return "; ".join(partes)
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
    talla, bateria_wh, motor, cuadro_material, componentes, modalidad.

    Devuelve la bici con los campos que se lograron completar.
    """
    faltan = (
        bici.peso_kg is None or bici.suspension_trasera is None or bici.ano is None
        or bici.km is None or bici.talla is None or bici.bateria_wh is None
        or bici.motor is None or bici.cuadro_material is None
        or bici.componentes is None or bici.modalidad is None
    )

    if not faltan:
        return bici

    # Paso 1: ficha del propio sitio (mas fiable)
    if url_ficha and SCRAPLING_AVAILABLE:
        try:
            detalle = _extraer_desde_ficha_sitio(url_ficha, bici.sitio)
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
    """Aplica los campos del detalle a la bici solo si faltan."""
    for campo, valor in detalle.items():
        if valor is not None and getattr(bici, campo, None) is None:
            setattr(bici, campo, valor)
    return bici
