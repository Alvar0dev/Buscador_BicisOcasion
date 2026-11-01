"""
config.py
Configuración central del buscador de bicicletas de ocasión.
Comentarios en español, tal como se solicitó.
"""

import os
from dataclasses import dataclass
from typing import List


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
        nombre="Tuvalum",
        base_url="https://www.tuvalum.com",
        seccion_emtb="https://www.tuvalum.com/es/bicicletas-electricas/montana/doble-suspension/",
    ),
    SitioObjetivo(
        nombre="Buhobike",
        base_url="https://www.buhobike.com",
        seccion_emtb="https://www.buhobike.com/electricas-trail-dobles",
    ),
    SitioObjetivo(
        nombre="Upway",
        base_url="https://upway.es",
        seccion_emtb="https://upway.es/collections/bicicleta-de-montana",
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
]

PESO_MAX_RECOMENDADO_KG: float = 19.0  # Peso deseado máximo (S3)
PESO_DESCARTE_KG: float = 21.0  # Modelos > 21 kg se descartan (S3)
MATERIALES_CUADRO_LIGERO: List[str] = ["carbono", "carbon", "fibra de carbono"]
MOTORES_LIGEROS: List[str] = [  # Priorizar cuadros carbono y motores ligeros (S3)
    "Shimano EP8",
    "Shimano EP801",
    "Shimano EP6",
    "Bosch SX",
    "Fazua",
    "TQ",
    "Mahle",
]

BATERIA_MIN_WH: int = 500  # > 500 Wh estricto (S4)

PRECIO_MIN_EUR: int = 2000  # Rango principal 2.000 € (S5)
PRECIO_MAX_EUR: int = 3000  # Rango principal 3.000 € (S5)
PRECIO_MAX_EXCEPCIONAL_EUR: int = 3300  # Oportunidad excepcional hasta 3.300 € (S6)

NOTA_MIN_AGUARDAR: float = 8.0  # Solo nota >= 8.0 se guarda/notifica (S8)

# ---------------------------------------------------------------------------
# TELEGRAM (S9)
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# ---------------------------------------------------------------------------
# BASE DE DATOS (S12)
# ---------------------------------------------------------------------------
DB_PATH: str = os.getenv("BUSCADOR_DB_PATH", "bicis_enviadas.db")

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

# Horario de ejecución (S10): todos los días a las 12:00
HORA_EJECUCION: str = "12:00"
