"""
scraper_base.py
Clase base para los scrapers de cada sitio.
Incluye fetch robusto con reintentos, cabeceras rotatorias y manejo de excepciones de red (S11, S13).
"""

import time
import random
import logging
from abc import ABC, abstractmethod
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from models import Bicicleta
import config as cfg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("scraper")


class BaseScraper(ABC):
    def __init__(self, sitio: cfg.SitioObjetivo) -> None:
        self.sitio = sitio
        self.session = requests.Session()
        self._rotar_cabeceras()

    def _rotar_cabeceras(self) -> None:
        """Asigna cabeceras rotatorias para evitar baneos básicos (S11)."""
        self.session.headers.update({
            "User-Agent": random.choice(cfg.USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        })

    def obtener_html(self, url: str, reintentos: int = 3) -> Optional[str]:
        """
        Descarga el HTML con reintentos y backoff exponencial.
        Si falla tras todos los intentos, devuelve None y registra el error (S13).
        Nota: si el sitio usa Cloudflare/JS, este método estático puede fallar;
        en ese caso se recomienda Playwright o curl_cffi (ver README).
        """
        for intento in range(1, reintentos + 1):
            try:
                self._rotar_cabeceras()
                resp = self.session.get(url, timeout=20)
                resp.raise_for_status()
                return resp.text
            except requests.RequestException as e:
                wait = 2 ** intento + random.uniform(0, 1)
                log.warning(
                    f"[{self.sitio.nombre}] Intento {intento}/{reintentos} falló para {url}: {e}. "
                    f"Reintentando en {wait:.1f}s"
                )
                time.sleep(wait)
        log.error(f"[{self.sitio.nombre}] No se pudo obtener {url} tras {reintentos} intentos.")
        return None

    def sopa(self, url: str) -> Optional[BeautifulSoup]:
        html = self.obtener_html(url)
        if html is None:
            return None
        return BeautifulSoup(html, "html.parser")

    @abstractmethod
    def extraer_bicicletas(self) -> List[Bicicleta]:
        """
        Extrae la lista de bicicletas de la sección objetivo.
        Cada subclase implementa sus propios selectores CSS.
        """
        raise NotImplementedError

    def url_absoluta(self, ruta_o_url: str) -> str:
        """Convierte una ruta relativa en URL absoluta del sitio."""
        if ruta_o_url.startswith("http"):
            return ruta_o_url
        return urljoin(self.sitio.base_url, ruta_o_url)

    def limpiar_texto(self, texto: Optional[str]) -> Optional[str]:
        if texto is None:
            return None
        return " ".join(texto.split()).strip()
