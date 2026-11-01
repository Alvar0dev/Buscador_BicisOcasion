"""
scraper_base.py
Clase base para los scrapers de cada sitio.
Incluye fetch robusto con 3 capas de fallback: curl_cffi → requests → Playwright.
Reintentos, cabeceras rotatorias y manejo de excepciones de red (S11, S13).
"""

import time
import random
import logging
from abc import ABC, abstractmethod
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from models import Bicicleta
import config as cfg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("scraper")

# Capa 1: curl_cffi (evade Cloudflare/JS básico)
try:
    from curl_cffi import requests as curl_requests
    CURL_CFFI_AVAILABLE = True
except ImportError:
    CURL_CFFI_AVAILABLE = False

# Capa 2: requests (estándar)
import requests

# Capa 3: Playwright (opcional, para Cloudflare fuerte/JS pesado)
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


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

    def _obtener_con_curl_cffi(self, url: str, timeout: int = 30) -> Optional[str]:
        """Capa 1: curl_cffi con impersonate para evadir detección de bot."""
        if not CURL_CFFI_AVAILABLE:
            return None
        try:
            resp = curl_requests.get(
                url,
                impersonate="chrome120",
                headers={
                    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
                },
                timeout=timeout,
            )
            if resp.status_code == 200:
                return resp.text
            log.warning(
                f"[{self.sitio.nombre}] curl_cffi devolvió {resp.status_code} para {url}"
            )
            return None
        except Exception as e:
            log.warning(
                f"[{self.sitio.nombre}] curl_cffi falló para {url}: {e}"
            )
            return None

    def _obtener_con_requests(self, url: str, timeout: int = 30) -> Optional[str]:
        """Capa 2: requests estándar con sesión y cabeceras rotatorias."""
        try:
            self._rotar_cabeceras()
            resp = self.session.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            log.warning(
                f"[{self.sitio.nombre}] requests falló para {url}: {e}"
            )
            return None

    def _obtener_con_playwright(self, url: str, timeout: int = 45) -> Optional[str]:
        """Capa 3: Playwright con Chromium (para Cloudflare fuerte o renderizado JS)."""
        if not PLAYWRIGHT_AVAILABLE:
            return None
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_extra_http_headers({
                    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
                })
                page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                html = page.content()
                browser.close()
                return html
        except Exception as e:
            log.warning(
                f"[{self.sitio.nombre}] Playwright falló para {url}: {e}"
            )
            return None

    def obtener_html(self, url: str, reintentos: int = 2) -> Optional[str]:
        """
        Descarga el HTML con 3 capas de fallback y reintentos.
        Orden: curl_cffi → requests → Playwright.
        Devuelve None si todas las capas fallan (S13).
        """
        # --- Capa 1: curl_cffi (2 reintentos, luego pasa a requests) ---
        for intento in range(1, reintentos + 1):
            html = self._obtener_con_curl_cffi(url)
            if html:
                return html
            wait = 2 ** intento + random.uniform(0, 1)
            log.warning(
                f"[{self.sitio.nombre}] Intento {intento}/{reintentos} (curl_cffi) falló para {url}. "
                f"Reintentando en {wait:.1f}s"
            )
            time.sleep(wait)

        # --- Capa 2: requests (2 reintentos, luego pasa a Playwright) ---
        for intento in range(1, reintentos + 1):
            html = self._obtener_con_requests(url)
            if html:
                return html
            wait = 2 ** intento + random.uniform(0, 1)
            log.warning(
                f"[{self.sitio.nombre}] Intento {intento}/{reintentos} (requests) falló para {url}. "
                f"Reintentando en {wait:.1f}s"
            )
            time.sleep(wait)

        # --- Capa 3: Playwright (un solo intento, es más lento) ---
        html = self._obtener_con_playwright(url)
        if html:
            return html

        log.error(
            f"[{self.sitio.nombre}] No se pudo obtener {url} tras todas las capas de fallback."
        )
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
