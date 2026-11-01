"""
scrapers/buhobike.py
Adaptador para Buhobike (buhobike.com).
Selectores CSS ajustados tras inspección real de la web (S14, S11).
Categoría objetivo: e-MTB trail doble suspensión (/electricas-trail-dobles).
"""

from typing import List
from bs4 import BeautifulSoup
from models import Bicicleta
from scraper_base import BaseScraper
import config as cfg
import re


class BuhobikeScraper(BaseScraper):
    def extraer_bicicletas(self) -> List[Bicicleta]:
        bicis: List[Bicicleta] = []
        soup = self.sopa(self.sitio.seccion_emtb)
        if soup is None:
            return bicis

        # Selectores observados en buhobike.com (listado de eléctricas)
        # Cada producto es un contenedor con anchor (URL), párrafo con título y texto de precio
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
                print(f"[Buhobike] Error parseando producto: {e}")
                continue

        return bicis

    def _parsear_precio(self, texto: str) -> float:
        """Extrae el primer número de precio del texto (ej. '5.999,00 €' o '3.599,00 € 3.599,00 €')."""
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
        """Extrae el ID numérico de la URL de producto de Buhobike.
        URL ejemplo: /electricas-trail-dobles/25574-127079-scott-strike-10-2027-...html
        """
        partes = url.rstrip("/").split("/")
        slug = partes[-1] if partes else ""
        # El ID suele ser el primer segmento numérico del slug
        match = re.match(r"(\d+)", slug)
        return match.group(1) if match else slug
