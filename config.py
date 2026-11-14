"""
config.py
Configuración central del buscador de bicicletas de ocasión.
Comentarios en español, tal como se solicitó.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

from dotenv import load_dotenv

BASE_DIR: Path = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class SitioObjetivo:
    nombre: str
    base_url: str
    seccion_emtb: str
    garantia_anos: int = 1  # Tiendas profesionales: garantía mecánica mínima 1 año


# ---------------------------------------------------------------------------
# SITIOS OBJETIVO (S14)
# Solo tiendas profesionales de reacondicionado con garantía mecánica ≥ 1 año.
# Bajo ningún concepto añadir Wallapop, Milanuncios ni foros de particulares.
# ---------------------------------------------------------------------------
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
    ),
]


# ---------------------------------------------------------------------------
# FILTROS ESTRICTOS (S1-S6)
# ---------------------------------------------------------------------------
TALLA_OBJETIVO: str = "M"  # Aprox. 165 cm - 179 cm (S1)

MODALIDADES_VALIDAS: List[str] = [  # S2
    "XC",
    "Cross Country",
    "Downcountry",
    "Light e-MTB",
    "Light eMTB",
    "Trail",
    "All Mountain",
]

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

NOTA_MIN_AGUARDAR: float = 8.0  # Solo nota >= 8.0 pasa filtros estrictos (S8)
NOTA_MIN_NOTIFICAR: float = 8.5  # Umbral para notificar por Telegram (fallback a Top N si ninguna llega)
TOP_N_NOTIFICAR: int = 3  # Cantidad de bicicletas más interesantes a enviar por Telegram

# ---------------------------------------------------------------------------
# GEMINI FLASH IA + CLASIFICADOR HÍBRIDO
# ---------------------------------------------------------------------------
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODELS: List[str] = [
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
]
GEMINI_API_URL: str = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

# ---------------------------------------------------------------------------
# TELEGRAM (S9)
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_API_URL: str = "https://api.telegram.org/bot{token}/sendMessage"
# Enviar heartbeat de pulso diario/ejecución a Telegram (TODO 2)
TELEGRAM_HEARTBEAT: bool = os.getenv("TELEGRAM_HEARTBEAT", "true").lower() in ("true", "1", "yes", "si")

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
