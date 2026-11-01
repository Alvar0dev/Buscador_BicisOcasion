"""
scrapers/tuvalum.py
Adaptador para Tuvalum (tuvalum.com).
ADVERTENCIA: el dominio tuvalum.com no resolvió desde este entorno al intentar
inspeccionarlo con ego-browser. Los selectores CSS son estimados basados en la
estructura típica de e-commerce y DEBEN verificarse tras inspección real.
URL tentativa según README: https://www.tuvalum.com/es/bicicletas-electricas/montana/doble-suspension/
"""

from typing import List
from bs4 import BeautifulSoup
from models import Bicicleta
from scraper_base import BaseScraper
import config as cfg
import re


class TuvalumScraper(BaseScraper):
    def extraer_bicicletas(self) -> List[Bicicleta]:
        bicis: List[Bicicleta] = []
        soup = self.sopa(self.sitio.seccion_emtb)
        if soup is None:
            return bicis

        # Selectores estimados (pendiente de verificación real en tuvalum.com)
        productos = soup.select(
            "article.product, .product-item, .product-grid-item, .product-card, "
            "div.product, .producto, .item-producto"
        )

        for p in productos:
            try:
                # Título: anchor dentro de párrafo, o h2/h3
                titulo_el = p.select_one("p > a, h2, h3, .product-title, .product-name")
                # Precio: texto que contenga €
                precio_el = p.select_one(".price, .current-price, .product-price, [class*='precio']")
                # Enlace: anchor con href
                link_el = p.select_one("a[href]")

                if not (titulo_el and precio_el and link_el):
                    continue

                titulo = self.limpiar_texto(titulo_el.get_text())
                precio = self._parsear_precio(precio_el.get_text())
                url = self.url_absoluta(link_el.get("href", ""))
                bici_id = self._extraer_id_url(url)

                if not titulo or precio <= 0:
                    continue

                bicis.append(Bicicleta(
                    sitio=self.sitio.nombre,
                    bici_id=bici_id,
                    titulo=titulo or "Sin título",
                    precio=precio,
                    url=url,
                    garantia_anos=self.sitio.garantia_anos,
                ))
            except Exception as e:
                print(f"[Tuvalum] Error parseando producto: {e}")
                continue

        return bicis

    def _parsear_precio(self, texto: str) -> float:
        """Extrae el primer número de precio del texto (ej. '2.500 €' o '2.500 € 3.000 €')."""
        match = re.search(r"([\d\.\s,\u00A0]+)\s*€", texto)
        if not match:
            return 0.0
        digitos = match.group(1)
        digitos = "".join(c for c in digitos if c.isdigit() or c in ".,")
        digitos = digitos.replace(".", "").replace(",", ".")
        try:
            return float(digitos)
        except ValueError:
            return 0.0

    def _extraer_id_url(self, url: str) -> str:
        """Extrae el ID de la URL de producto de Tuvalum."""
        partes = url.rstrip("/").split("/")
        slug = partes[-1] if partes else ""
        match = re.match(r"(\d+)", slug)
        return match.group(1) if match else slug
