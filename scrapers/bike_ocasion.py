"""
scrapers/bike_ocasion.py
Adaptador para Bike Ocasión (bike-ocasion.com).
Selectores CSS ajustados tras inspección real de la web (S14, S11).
NOTA: la URL de categoría se corrigió en config.py (sección_emtb).
"""

from typing import List, Optional
from bs4 import BeautifulSoup
from models import Bicicleta
from scraper_base import BaseScraper
import config as cfg
import re


class BikeOcasionScraper(BaseScraper):
    def extraer_bicicletas(self) -> List[Bicicleta]:
        bicis: List[Bicicleta] = []
        soup = self.sopa(self.sitio.seccion_emtb)
        if soup is None:
            return bicis

        # Selectores reales observados en bike-ocasion.com (página de producto y listado)
        # Cada producto es un <article> o contenedor con título, precio y enlace
        productos = soup.select("article.product, .product-item, .product-grid-item, .product-card")

        for p in productos:
            try:
                # Título: puede ser .product_name (PPD) o .product-title / h2 / h3 (listado)
                titulo_el = p.select_one(".product_name, .product-title, h2, h3")
                # Precio: .price en PPD, o texto con € en listado
                precio_el = p.select_one(".price, .current-price, .product-price")
                # Enlace: <a> con href
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
                print(f"[BikeOcasion] Error parseando producto: {e}")
                continue

        return bicis

    def _parsear_precio(self, texto: str) -> float:
        """Extrae el primer número de precio del texto (ej. '3.179 €' o '3.179 € 8.000 €')."""
        # Tomar solo el primer bloque numérico antes de €
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
        """Extrae el ID numérico de la URL de producto de Bike Ocasión."""
        # URL ejemplo: /bicicletas-electricas-de-montana-doble-suspension/463682-nombre-8445881728148.html
        partes = url.rstrip("/").split("/")
        slug = partes[-1] if partes else ""
        # El ID suele ser el primer segmento numérico del slug
        match = re.match(r"(\d+)", slug)
        return match.group(1) if match else slug
