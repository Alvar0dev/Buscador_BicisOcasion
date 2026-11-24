"""
config.py
Configuración central del buscador de bicicletas de ocasión.
Comentarios en español, tal como se solicitó.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

BASE_DIR: Path = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class SitioObjetivo:
    nombre: str
    base_url: str
    seccion_emtb: str
    garantia_anos: int = 1  # Tiendas profesionales: garantía mecánica mínima 1 año
    es_tienda_nueva: bool = False  # Tiendas oficiales con stock nuevo 0 km en España


# ---------------------------------------------------------------------------
# SITIOS OBJETIVO (S14 + Wallapop geolocalizado)
# Tiendas profesionales de reacondicionado (índices 0..3) y anuncios de Wallapop
# geolocalizados en un radio configurable alrededor de Fuenlabrada (índice 4).
# ---------------------------------------------------------------------------
WALLAPOP_LAT: float = float(os.getenv("WALLAPOP_LAT", "40.2842"))
WALLAPOP_LON: float = float(os.getenv("WALLAPOP_LON", "-3.7942"))
WALLAPOP_RADIO_KM: int = int(os.getenv("WALLAPOP_RADIO_KM", "50"))
WALLAPOP_PERMITIR_NACIONAL: bool = False  # Estricto <= WALLAPOP_RADIO_KM (50 km de Fuenlabrada)
WALLAPOP_UNICORN_QUERIES: List[str] = [
    "BH iLynx Race",
    "BH iLynx Trail",
    "Orbea Rise",
    "Cannondale Moterra SL",
    "Scott Lumen",
    "Wilier Urta Hybrid",
    "Focus VAM2",
    "Focus Jam2 SL",
    "BMC Fourstroke AMP",
]

SITIOS: List[SitioObjetivo] = [
    SitioObjetivo(
        nombre="Bike Ocasión",
        base_url="https://www.bike-ocasion.com",
        seccion_emtb="https://www.bike-ocasion.com/bicicletas-electricas-de-montana-doble-suspension-2020",
    ),
    SitioObjetivo(
        nombre="Buhobike",
        base_url="https://www.buhobike.com",
        seccion_emtb="https://www.buhobike.com/3230-electricas-trail-dobles?order=product.price.asc",
        es_tienda_nueva=True,
    ),
    SitioObjetivo(
        nombre="Upway",
        base_url="https://upway.es",
        seccion_emtb="https://upway.es/collections/doble-suspension",
    ),
    SitioObjetivo(
        nombre="Mammoth",
        base_url="https://www.mammothbikes.com",
        seccion_emtb="https://www.mammothbikes.com/bicicletas-electricas-mtb-dobles-rally-xc/c-3104",
        garantia_anos=3,
        es_tienda_nueva=True,
    ),
    SitioObjetivo(
        nombre="Wallapop",
        base_url="https://es.wallapop.com",
        seccion_emtb="https://api.wallapop.com/api/v3/search",
        garantia_anos=0,  # Particulares por defecto (1 si is_refurbished / has_warranty)
    ),
    SitioObjetivo(
        nombre="Sanferbike",
        base_url="https://www.sanferbike.com",
        seccion_emtb="https://www.sanferbike.com/es/bicicletas-electricas-montana-doble-suspension-22838?order=product.price.asc",
        garantia_anos=3,
        es_tienda_nueva=True,
    ),
    SitioObjetivo(
        nombre="Bicimarket",
        base_url="https://www.bicimarket.com",
        seccion_emtb="https://www.bicimarket.com/es/585-ebike-mtb-29?q=Tipo+eBike+MTB+29-Doble+Suspensi%C3%B3n&order=product.price.asc",
        garantia_anos=3,
        es_tienda_nueva=True,
    ),
    SitioObjetivo(
        nombre="Escapa",
        base_url="https://www.escapa.com",
        seccion_emtb="https://www.escapa.com/electricas/electrica-btt/btt-doble?sort=priceasc",
        garantia_anos=3,
        es_tienda_nueva=True,
    ),
    SitioObjetivo(
        nombre="Fabregues",
        base_url="https://fabreguesbicicletas.com",
        seccion_emtb="https://fabreguesbicicletas.com/es/bicicletas/electricas/e-bike-btt/dobles?order=product.price.asc",
        garantia_anos=3,
        es_tienda_nueva=True,
    ),
]

_TOKENS_NO_NUEVA = (
    "segunda-mano",
    "segunda mano",
    "segundamano",
    "reacondicionad",
    "/ocasion",
    "test-ride",
    "test ride",
    "medio uso",
    "medio-uso",
    "valor de recompra",
)


def es_sitio_tienda_nueva(
    sitio: Optional[str],
    url: Optional[str] = None,
    texto: Optional[str] = None,
) -> bool:
    """True si el portal corresponde a una tienda oficial nueva (0 km) sin indicios de ocasión/test-ride."""
    txt_norm = f"{url or ''} {texto or ''}".lower()
    if any(tok in txt_norm for tok in _TOKENS_NO_NUEVA) or re.search(r"\bdemo\b", txt_norm):
        return False

    sitio_low = (sitio or "").strip().lower()
    url_low = (url or "").strip().lower()
    for s in SITIOS:
        if not s.es_tienda_nueva:
            continue
        if sitio_low and s.nombre.lower() == sitio_low:
            return True
        if url_low:
            dom = s.base_url.lower().replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0]
            if dom and dom in url_low:
                return True
    return False


_MAPA_TALLAS = {
    "XS": "XS", "S1": "XS",
    "S": "S", "SM": "S", "SMALL": "S", "PEQUEÑA": "S", "PEQUENA": "S", "S2": "S",
    "M": "M", "MD": "M", "S/M": "M", "S_M": "M", "MEDIUM": "M", "MEDIANA": "M", "S3": "M",
    "ML": "ML", "M/L": "ML", "M_L": "ML",
    "L": "L", "LA": "L", "LG": "L", "LARGE": "L", "GRANDE": "L", "S4": "L",
    "XL": "XL", "S5": "XL",
    "XXL": "XXL", "S6": "XXL",
}


def normalizar_codigo_talla(raw: Optional[str]) -> Optional[str]:
    """Normaliza códigos de talla ('MD'/'M/L' -> 'M', 'SM' -> 'S', 'LA'/'LG' -> 'L')."""
    if not raw:
        return None
    limpio = re.sub(r"\s+", "", raw.strip().upper())
    return _MAPA_TALLAS.get(limpio)


def seleccionar_talla_disponible(tallas: List[str]) -> Optional[str]:
    """Devuelve TALLA_OBJETIVO ('M') si está entre las disponibles; si no, la primera disponible."""
    normalizadas = [t for t in (normalizar_codigo_talla(x) for x in tallas) if t]
    if not normalizadas:
        return None
    objetivo = TALLA_OBJETIVO.upper()
    if objetivo in normalizadas:
        return objetivo
    return normalizadas[0]


# ---------------------------------------------------------------------------
# FILTROS ESTRICTOS (S1-S6)
# ---------------------------------------------------------------------------
TALLA_OBJETIVO: str = "M"  # Aprox. 165 cm - 179 cm (S1)

MODALIDADES_VALIDAS: List[str] = [  # S2 — Estrictamente XC / Cross Country / Downcountry (<= 130 mm)
    "XC",
    "Cross Country",
    "Downcountry",
]
RECORRIDO_MAX_XC_MM: int = 130  # Límite máximo estricto de recorrido XC/Downcountry (descarta Trail >= 140 mm)

PESO_MAX_RECOMENDADO_KG: float = 19.0  # Peso deseado máximo (S3)
PESO_DESCARTE_KG: float = 21.0  # Modelos >= 21 kg se descartan (S3)
MATERIALES_CUADRO_LIGERO: List[str] = ["carbono", "carbon", "fibra de carbono"]
MOTORES_LIGEROS: List[str] = [  # Priorizar cuadros carbono y motores ligeros (S3)
    "Shimano EP8",
    "Shimano EP801",
    "Shimano EP6",
    "Bosch SX",
    "Fazua",
    "TQ",
    "Mahle",
    "Specialized SL",
    "BH 2EXMAG",
]

BATERIA_MIN_WH: int = 500  # > 500 Wh estricto (S4)

PRECIO_MIN_EUR: int = 2000  # Rango principal 2.000 € (S5)
PRECIO_MAX_EUR: int = 3000  # Rango principal 3.000 € (S5)
PRECIO_MAX_EXCEPCIONAL_EUR: int = 3300  # Oportunidad excepcional hasta 3.300 € (S6)
PRECIO_MAX_UNICORNIO_XC_EUR: int = 3500  # Margen <= 3.500 € para unicornios XC >= 600 Wh y <= 500 km / o BF + extender

# Canal exclusivo Black Friday (bicis nuevas o seminuevas <= 3.500 €, respaldo hasta 4.000 €)
PRECIO_MAX_BLACK_FRIDAY_EUR: int = 3500
PRECIO_RESPALDO_BLACK_FRIDAY_EUR: int = 4000
KM_MAX_BLACK_FRIDAY: int = 50
KM_MAX_SEMINUEVA_BLACK_FRIDAY: int = 500
DESCUENTO_MIN_BLACK_FRIDAY_PCT: float = 35.0
NOTA_MIN_BLACK_FRIDAY: float = 7.5
BLACK_FRIDAY_TOP_N: int = 5
BLACK_FRIDAY_FALLBACK_TOP_N: int = 3

NOTA_MIN_AGUARDAR: float = 8.0  # Solo nota >= 8.0 pasa filtros estrictos (S8)
NOTA_MIN_NOTIFICAR: float = 8.5  # Umbral para notificar por Telegram (fallback a Top N si ninguna llega)
TOP_N_NOTIFICAR: int = 3  # Cantidad de bicicletas más interesantes a enviar por Telegram

# ---------------------------------------------------------------------------
# GEMINI FLASH IA + CLASIFICADOR HÍBRIDO
# ---------------------------------------------------------------------------
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODELS: List[str] = [
    "gemini-3.5-flash-lite",
    "gemini-3-flash-preview",
    "gemini-3.5-flash",
]
GEMINI_API_URL: str = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

# ---------------------------------------------------------------------------
# TELEGRAM (S9)
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_BOT_TOKEN_BLACK_FRIDAY: str = os.getenv("TELEGRAM_BOT_TOKEN_BLACK_FRIDAY", "")
TELEGRAM_CHAT_ID_BLACK_FRIDAY: str = os.getenv("TELEGRAM_CHAT_ID_BLACK_FRIDAY", "") or TELEGRAM_CHAT_ID
TELEGRAM_API_URL: str = "https://api.telegram.org/bot{token}/sendMessage"
# Enviar heartbeat de pulso diario/ejecución a Telegram (TODO 2)
TELEGRAM_HEARTBEAT: bool = os.getenv("TELEGRAM_HEARTBEAT", "true").lower() in ("true", "1", "yes", "si")
# Silenciar ofertas normales en Telegram (solo suenan los Mega Chollos >= 9.0 y >50% dto) (TODO 3)
TELEGRAM_SILENCIAR_OFERTAS_NORMALES: bool = os.getenv("TELEGRAM_SILENCIAR_OFERTAS_NORMALES", "true").lower() in ("true", "1", "yes", "si")

# ---------------------------------------------------------------------------
# BASE DE DATOS (S12)
# ---------------------------------------------------------------------------
DB_PATH: str = os.getenv("BUSCADOR_DB_PATH", str(BASE_DIR / "bicis_enviadas.db"))

# ---------------------------------------------------------------------------
# CABECERAS ROTATORIAS (S11)
# ---------------------------------------------------------------------------
USER_AGENTS: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]

# ---------------------------------------------------------------------------
# PROXIES (S13, opcional)
# ---------------------------------------------------------------------------
# Scrapling trae ProxyRotator integrado. Configurar proxies rotatorios
# para evitar bloqueos por IP en sitios con Cloudflare agresivo.
# Variables de entorno:
#   PROXY_LIST: lista de proxies separados por coma o líneas (ej. "http://user:pass@ip:port,http://...")
#   PROXY_ROTATION: "cyclic" o "random" / "aleatorio" (default: cyclic)
_raw_proxy_list = os.getenv("PROXY_LIST", "")
PROXY_LIST: List[str] = [
    p.strip().strip("'\"")
    for p in re.split(r"[\n,]+", _raw_proxy_list)
    if p.strip().strip("'\"")
]
PROXY_ROTATION: str = os.getenv("PROXY_ROTATION", "cyclic").strip().lower()

# Horario de ejecución (S10): todos los días a las 12:30
HORA_EJECUCION: str = "12:30"
