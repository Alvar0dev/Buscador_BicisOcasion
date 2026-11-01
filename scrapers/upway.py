"""
scrapers/upway.py
Adaptador para Upway (upway.es).
Selectores CSS ajustados tras inspección real de la web (S14, S11).
Categoría objetivo: bicicletas eléctricas de montaña (/collections/bicicleta-de-montana).

Estructura observada en upway.es:
  <a class="w-full" href="/products/moustache-samedi-29-trail-3-rk7fu0">
    Más vendida Moustache Samedi 29 Trail 3 2023 1m69-1m85 10.152 km 1.999 € 5.499 € nuevo
  </a>
"""

from typing import List
from bs4 import BeautifulSoup
from models import Bicicleta
from scraper_base import BaseScraper
import config as cfg
import re


class UpwayScraper(BaseScraper):
    def extraer_bicicletas(self) -> List[Bicicleta]:
        bicis: List[Bicicleta] = []
        soup = self.sopa(self.sitio.seccion_emtb)
        if soup is None:
            return bicis

        # Selectores reales observados en upway.es:
        # Enlaces a producto: <a class="w-full" href="/products/<slug>-<id>">
        productos = soup.select('a.w-full[href*="/products/"]')

        for p in productos:
            try:
                href = p.get("href", "")
                if not href:
                    continue

                url = self.url_absoluta(href)

                # bici_id: último segmento del slug (ej. "rk7fu0")
                slug = href.rstrip("/").split("/")[-1]
                bici_id = slug.split("-")[-1] if slug else slug

                # Título: texto del enlace con espacios entre elementos hijos
                texto_completo = p.get_text(" ", strip=True)
                texto_completo = self.limpiar_texto(texto_completo)
                titulo = self._extraer_titulo_simple(texto_completo)

                # Precio: primer valor en € encontrado en el texto
                precio = self._parsear_precio(texto_completo)

                if not titulo or precio <= 0:
                    continue

                bicis.append(Bicicleta(
                    sitio=self.sitio.nombre,
                    bici_id=bici_id,
                    titulo=titulo,
                    precio=precio,
                    url=url,
                    garantia_anos=self.sitio.garantia_anos,
                ))
            except Exception as e:
                print(f"[Upway] Error parseando producto: {e}")
                continue

        return bicis

    def _extraer_titulo_simple(self, texto: str) -> str:
        """
        Limpieza básica del título de Upway.
        Elimina precios y kilometraje del final, pero conserva etiquetas
        informativas al inicio ("Más vendida", "Recién llegada", etc.).
        """
        # Eliminar precios al final (ej. "1.999 € 5.499 €")
        texto = re.sub(r"\s*[\d\.\s,]+\s*€\s*[\d\.\s,]+\s*€\s*$", "", texto)
        texto = re.sub(r"\s*[\d\.\s,]+\s*€\s*$", "", texto)
        
        # Eliminar kilometraje suelto al final (ej. "10.152 km", "km")
        texto = re.sub(r"\s*\d[\d.\s]*\s*km\b\s*$", "", texto)
        texto = re.sub(r"\s*km\b\s*$", "", texto)
        
        # Eliminar años sueltos al final (ej. "2023")
        texto = re.sub(r"\s+\d{4}\s*$", "", texto)
        
        return texto.strip()

    def _parsear_precio(self, texto: str) -> float:
        """Extrae el primer número de precio del texto (ej. '1.999 € 5.499 € nuevo')."""
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
