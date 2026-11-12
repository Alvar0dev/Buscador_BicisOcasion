"""
scraper_base.py
Clase base para los scrapers de cada sitio.
Motor de scraping: Scrapling (https://github.com/D4Vinci/Scrapling).

Capas de fetch:
  1. Fetcher (HTTP con impersonación TLS de navegador) - rápido, ideal para sitios sin Cloudflare agresivo.
  2. StealthyFetcher (navegador stealth con solve_cloudflare=True) - para Cloudflare / JS pesado.

La interfaz pública (sopa, url_absoluta, limpiar_texto) se mantiene igual que antes para que
los scrapers existentes sigan funcionando sin cambios. Internamente ahora usa Scrapling.
(S11, S13)
"""

import time
import random
import logging
import re
from abc import ABC, abstractmethod
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from models import Bicicleta
import config as cfg

log = logging.getLogger("scraper")

# Scrapling: Fetcher (HTTP stealth) y StealthyFetcher (navegador + Cloudflare solver)
try:
    from scrapling.fetchers import (
        Fetcher,
        StealthyFetcher,
        FetcherSession,
        StealthySession,
        ProxyRotator,
    )
    from scrapling.engines.toolbelt.proxy_rotation import cyclic_rotation
    SCRAPLING_AVAILABLE = True
except ImportError:
    SCRAPLING_AVAILABLE = False


def random_rotation(proxies: List[str], current_index: int):
    """Estrategia de rotación aleatoria para ProxyRotator."""
    idx = random.randrange(len(proxies))
    return proxies[idx], idx


def crear_proxy_rotator(
    proxies: Optional[List[str]] = None,
    rotacion: Optional[str] = None,
) -> Optional[object]:
    """
    Crea una instancia de ProxyRotator de Scrapling con la estrategia configurada.
    Devuelve None si no hay proxies configurados o Scrapling no está disponible.
    """
    if not SCRAPLING_AVAILABLE:
        return None
    raw_lista = proxies if proxies is not None else cfg.PROXY_LIST
    lista = [p.strip().strip("'\"") for p in raw_lista if p and p.strip().strip("'\"")]
    if not lista:
        return None
    estrategia = cfg.PROXY_ROTATION if rotacion is None else rotacion
    strategy_fn = (
        random_rotation
        if str(estrategia).lower() in ("random", "aleatorio")
        else cyclic_rotation
    )
    try:
        return ProxyRotator(proxies=list(lista), strategy=strategy_fn)
    except Exception as e:
        log.warning(f"[ProxyRotator] No se pudo inicializar la rotación de proxies: {e}")
        return None


class BaseScraper(ABC):
    usar_stealth_directo: bool = False

    def __init__(self, sitio: cfg.SitioObjetivo) -> None:
        self.sitio = sitio
        self._delay_ultimo_request: float = 0.0
        self._ultimo_status_http: Optional[int] = None
        self._proxy_rotator = crear_proxy_rotator()
        self._session_proxy = self._crear_sesion_con_proxy()

    def _crear_sesion_con_proxy(self):
        """
        Crea una sesión FetcherSession con ProxyRotator si hay proxies configurados.
        Devuelve None si no hay proxies o Scrapling no está disponible.
        """
        if not SCRAPLING_AVAILABLE or not self._proxy_rotator:
            return None
        try:
            return FetcherSession(proxy_rotator=self._proxy_rotator)
        except Exception as e:
            log.warning(
                f"[{self.sitio.nombre}] No se pudo crear sesión con proxy: {e}"
            )
            return None

    def _espera_cortesa(self) -> None:
        """Pequeno delay aleatorio entre requests para no saturar el sitio objetivo (S13)."""
        delay = random.uniform(1.0, 2.5)
        if self._delay_ultimo_request > 0:
            transcurrido = time.time() - self._delay_ultimo_request
            if transcurrido < delay:
                time.sleep(delay - transcurrido)
        self._delay_ultimo_request = time.time()

    def _obtener_con_fetcher(self, url: str, timeout: int = 30) -> Optional[str]:
        """Capa 1: Scrapling Fetcher con impersonacion de Chrome (TLS fingerprint + headers)."""
        if not SCRAPLING_AVAILABLE:
            return None
        try:
            if self._session_proxy is not None:
                # Usar sesión con proxy rotator
                page = self._session_proxy.get(url, impersonate="chrome120", timeout=timeout)
            elif self._proxy_rotator is not None:
                page = Fetcher.get(
                    url, impersonate="chrome120", timeout=timeout, proxy_rotator=self._proxy_rotator
                )
            else:
                page = Fetcher.get(url, impersonate="chrome120", timeout=timeout)
            self._ultimo_status_http = page.status
            if page.status == 200:
                return page.html_content
            log.warning(
                f"[{self.sitio.nombre}] Fetcher devolvio {page.status} para {url}"
            )
            return None
        except Exception as e:
            log.warning(
                f"[{self.sitio.nombre}] Fetcher fallo para {url}: {e}"
            )
            return None

    def _obtener_con_stealth(self, url: str, timeout: int = 60) -> Optional[str]:
        """Capa 2: Scrapling StealthyFetcher con solve_cloudflare (navegador stealth)."""
        if not SCRAPLING_AVAILABLE:
            return None
        try:
            kwargs = {
                "headless": True,
                "solve_cloudflare": True,
                "timeout": timeout,
            }
            if self._proxy_rotator is not None:
                kwargs["proxy_rotator"] = self._proxy_rotator

            page = StealthyFetcher.fetch(url, **kwargs)
            self._ultimo_status_http = page.status
            if page.status == 200:
                return page.html_content
            log.warning(
                f"[{self.sitio.nombre}] StealthyFetcher devolvio {page.status} para {url}"
            )
            return None
        except Exception as e:
            log.warning(
                f"[{self.sitio.nombre}] StealthyFetcher fallo para {url}: {e}"
            )
            return None

    def obtener_html(self, url: str, reintentos: int = 2) -> Optional[str]:
        """
        Descarga el HTML con capas de fallback usando Scrapling.
        Orden: Fetcher (HTTP rapido) -> StealthyFetcher (Cloudflare/JS).
        Si `usar_stealth_directo` es True o Fetcher recibe bloqueo 403/503 de Cloudflare,
        salta directamente a StealthyFetcher sin malgastar reintentos HTTP.
        Devuelve None si todas las capas fallan (S13).
        """
        self._espera_cortesa()

        if not self.usar_stealth_directo:
            # --- Capa 1: Fetcher (reintentos con backoff) ---
            for intento in range(1, reintentos + 1):
                self._ultimo_status_http = None
                html = self._obtener_con_fetcher(url)
                if html:
                    return html
                if self._ultimo_status_http in (403, 503):
                    log.info(
                        f"[{self.sitio.nombre}] Bloqueo Cloudflare ({self._ultimo_status_http}) detectado en {url}. "
                        f"Saltando directamente a StealthyFetcher."
                    )
                    break
                wait = 2 ** intento + random.uniform(0, 1)
                log.warning(
                    f"[{self.sitio.nombre}] Intento {intento}/{reintentos} (Fetcher) fallo para {url}. "
                    f"Reintentando en {wait:.1f}s"
                )
                time.sleep(wait)
            self._espera_cortesa()

        # --- Capa 2: StealthyFetcher (para Cloudflare agresivo / JS pesado) ---
        html = self._obtener_con_stealth(url)
        if html:
            return html

        log.error(
            f"[{self.sitio.nombre}] No se pudo obtener {url} tras todas las capas de Scrapling."
        )
        return None

    def sopa(self, url: str) -> Optional[BeautifulSoup]:
        """Devuelve BeautifulSoup construido desde el HTML obtenido por Scrapling.

        Mantiene retrocompatibilidad con los scrapers existentes que usan
        soup.select(), soup.find(), etc.
        """
        html = self.obtener_html(url)
        if html is None:
            return None
        # page.html_content de Scrapling es un TextHandler (subclase de str);
        # convertirlo explícitamente a str para evitar problemas con BeautifulSoup.
        html_str = str(html)
        return BeautifulSoup(html_str, "html.parser")

    def respuesta_scrapling(self, url: str):
        """Devuelve el objeto Response nativo de Scrapling para un URL.

        Permite usar selectores nativos de Scrapling (.css, .xpath, .getall, ...)
        en lugar de BeautifulSoup. Devuelve None si falla.
        """
        if not SCRAPLING_AVAILABLE:
            return None
        self._espera_cortesa()
        try:
            if self._session_proxy is not None:
                page = self._session_proxy.get(url, impersonate="chrome120", timeout=30)
            elif self._proxy_rotator is not None:
                page = Fetcher.get(
                    url, impersonate="chrome120", timeout=30, proxy_rotator=self._proxy_rotator
                )
            else:
                page = Fetcher.get(url, impersonate="chrome120", timeout=30)
            if page.status == 200:
                return page
            return None
        except Exception:
            try:
                stealth_kwargs = {
                    "headless": True,
                    "solve_cloudflare": True,
                    "timeout": 60,
                }
                if self._proxy_rotator is not None:
                    stealth_kwargs["proxy_rotator"] = self._proxy_rotator
                page = StealthyFetcher.fetch(url, **stealth_kwargs)
                if page.status == 200:
                    return page
            except Exception:
                pass
        return None

    def extraer_bicicletas_paginado(
        self,
        construir_url_pagina,
        max_paginas: int = 5,
    ) -> List[Bicicleta]:
        """
        Extrae bicicletas de múltiples páginas de un listado.

        Args:
            construir_url_pagina: función que recibe el número de página (int)
                y devuelve la URL absoluta de esa página.
            max_paginas: límite máximo de páginas a recorrer (evita bucles infinitos).

        Devuelve la lista acumulada de bicicletas de todas las páginas.
        Se detiene cuando una página devuelve 0 productos o se alcanza max_paginas.
        """
        todas: List[Bicicleta] = []

        for pagina in range(1, max_paginas + 1):
            url = construir_url_pagina(pagina)
            log.info(f"[{self.sitio.nombre}] Página {pagina}: {url}")

            soup = self.sopa(url)
            if soup is None:
                log.warning(f"[{self.sitio.nombre}] Página {pagina}: no se pudo obtener HTML. Deteniendo paginación.")
                break

            # Contar productos antes de extraer (para saber si la página tiene contenido).
            productos = soup.select(
                "article.ajax_block_product, article.js-product-miniature, article.product, "
                ".product-item, .product-grid-item, .product-card"
            )
            if not productos:
                log.info(f"[{self.sitio.nombre}] Página {pagina}: 0 productos. Fin de paginación.")
                break

            # Extraer bicicletas de esta página reutilizando la lógica del scraper.
            # Sobrescribimos temporalmente la URL del listado para que `extraer_bicicletas`
            # lea de esta página. Cada scraper implementa su propia lógica en `extraer_bicicletas`,
            # así que aquí delegamos al método de instancia pero con la URL de esta página.
            bicis_pagina = self._extraer_de_sopa(soup)
            if not bicis_pagina:
                log.info(f"[{self.sitio.nombre}] Página {pagina}: 0 bicicletas extraídas. Fin de paginación.")
                break

            todas.extend(bicis_pagina)
            log.info(f"[{self.sitio.nombre}] Página {pagina}: {len(bicis_pagina)} bicicletas extraídas (total {len(todas)}).")

        return todas

    def _extraer_de_sopa(self, soup: BeautifulSoup) -> List[Bicicleta]:
        """
        Extrae bicicletas de un objeto BeautifulSoup ya parseado.
        Cada subclase debe implementar este método si quiere usar paginación.
        Por defecto devuelve lista vacía (sin paginación).
        """
        return []

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

    @staticmethod
    def es_tarjeta_no_disponible(elemento_tag=None, texto_tarjeta: str = "") -> bool:
        """
        Detecta si una tarjeta o producto figura como Reservada, Agotada, Vendida o Sin stock.
        Verifica tanto clases CSS de PrestaShop/tiendas como etiquetas de texto con bordes de palabra.
        """
        if elemento_tag is not None and hasattr(elemento_tag, "get"):
            clases_propias = " ".join(elemento_tag.get("class") or []).lower()
            if any(
                c in clases_propias
                for c in (
                    "product-unavailable",
                    "out-of-stock",
                    "out_of_stock",
                    "sold-out",
                    "agotado",
                    "reservado",
                    "sin-stock",
                )
            ):
                return True

            if hasattr(elemento_tag, "select_one"):
                badge_no_disp = elemento_tag.select_one(
                    ".product-unavailable, .out-of-stock, .out_of_stock, .sold-out, "
                    ".agotado, .reservado, .sin-stock, .product-flag.out_of_stock"
                )
                if badge_no_disp is not None:
                    return True

            if not texto_tarjeta and hasattr(elemento_tag, "get_text"):
                texto_tarjeta = elemento_tag.get_text(" ", strip=True)

        if texto_tarjeta:
            if re.search(
                r"\b(?:reservad[oa]s?|agotad[oa]s?|vendid[oa]s?|sin\s+stock|out\s+of\s+stock|fuera\s+de\s+stock|no\s+disponible)\b",
                texto_tarjeta,
                re.IGNORECASE,
            ):
                return True

        return False
