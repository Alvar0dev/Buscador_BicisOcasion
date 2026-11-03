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

                # Enriquecer con datos reales de la ficha de producto (solo si está en rango de precio
                # para no saturar requests; las fuera de rango se descartan por precio de todas formas).
                detalle = {}
                if cfg.PRECIO_MIN_EUR <= precio <= cfg.PRECIO_MAX_EXCEPCIONAL_EUR:
                    detalle = self._obtener_detalle_producto(url)

                bicis.append(Bicicleta(
                    sitio=self.sitio.nombre,
                    bici_id=bici_id,
                    titulo=titulo,
                    precio=precio,
                    url=url,
                    talla=detalle.get("talla"),
                    bateria_wh=detalle.get("bateria_wh"),
                    km=detalle.get("km"),
                    motor=detalle.get("motor"),
                    cuadro_material=detalle.get("cuadro_material"),
                    componentes=detalle.get("componentes"),
                    ano=detalle.get("ano"),
                    peso_kg=detalle.get("peso_kg"),
                    garantia_anos=self.sitio.garantia_anos,
                ))
            except Exception as e:
                print(f"[Upway] Error parseando producto: {e}")
                continue

        return bicis

    def _obtener_detalle_producto(self, url: str) -> dict:
        """
        Entra a la ficha de producto de Upway y extrae los campos reales:
        talla, año, kilometraje. Devuelve un dict con los campos encontrados.
        """
        detalle: dict = {}
        soup = self.sopa(url)
        if soup is None:
            return detalle

        # --- Año: dt='Año' -> dd ---
        dt_ano = soup.find("dt", string=lambda t: t and t.strip() == "Año")
        if dt_ano:
            dd = dt_ano.find_next_sibling("dd")
            if dd:
                match = re.search(r"\b(20\d{2})\b", dd.get_text(strip=True))
                if match:
                    detalle["ano"] = int(match.group(1))

        # --- Talla: dt='Talla' -> dd ---
        dt_talla = soup.find("dt", string=lambda t: t and t.strip() == "Talla")
        if dt_talla:
            dd = dt_talla.find_next_sibling("dd")
            if dd:
                talla = self.limpiar_texto(dd.get_text())
                # Valor ejemplo: "M: ideal para ciclistas entre 1m69 - 1m85" -> extraer "M"
                detalle["talla"] = talla.split(":")[0].strip() if ":" in talla else talla.split()[0]

        # --- Kilometraje: buscar span con número + km ---
        for el in soup.find_all(string=lambda t: t and "km" in t.lower()):
            texto = el.strip()
            match = re.search(r"([\d.,]+)\s*km\b", texto, re.IGNORECASE)
            if match:
                km_str = match.group(1).replace(".", "").replace(",", "")
                try:
                    detalle["km"] = int(km_str)
                    break
                except ValueError:
                    pass

        return detalle

    def _extraer_titulo_simple(self, texto: str) -> str:
        """
        Limpieza del título de Upway.
        Elimina etiquetas informativas al inicio, rangos de talla, precios,
        kilometraje y años sueltos del final, dejando solo el nombre del modelo.
        """
        # Normalizar espacios no quebrables estrechos (U+202F) a espacio normal
        texto = texto.replace("\u202f", " ")

        # Eliminar etiquetas informativas al inicio (ej. "Más vendida", "Recién llegada", "Mejor precio")
        # Se aplican en bucle por si hay varias seguidas ("Mejor precio Recién llegada")
        while True:
            nuevo = re.sub(r"^(Más vendida|Recién llegada|Mejor precio|Oferta|Destacada)\s+", "", texto, flags=re.IGNORECASE)
            if nuevo == texto:
                break
            texto = nuevo

        # Eliminar rangos de talla (ej. "1m64-1m77", "1m69-1m85", "1m80-1m93")
        texto = re.sub(r"\s*\d+m\d+-\d+m\d+\s*", " ", texto)

        # Eliminar "<" o ">" sueltos al final (ej. de "< 5 km")
        texto = re.sub(r"\s*[<>]\s*$", "", texto)

        # Eliminar "nuevo" / "nueva" al final (antes de los precios, para que el regex de precios coincida)
        texto = re.sub(r"\s*(nuevo|nueva)\s*$", "", texto, flags=re.IGNORECASE)

        # Eliminar kilometraje suelto (ej. "10.152 km", "530 km")
        texto = re.sub(r"\s*\d[\d.,\s]*\s*km\b\s*", " ", texto, flags=re.IGNORECASE)

        # Eliminar precios al final (ej. "1.999 € 5.499 €")
        texto = re.sub(r"\s*[\d\.\s,]+\s*€\s*[\d\.\s,]+\s*€\s*$", "", texto)
        texto = re.sub(r"\s*[\d\.\s,]+\s*€\s*$", "", texto)

        # Eliminar años sueltos al final (ej. "2023")
        texto = re.sub(r"\s+\d{4}\s*$", "", texto)

        # Eliminar caracteres sueltos no alfanuméricos al final (ej. "<", ">", "-")
        texto = re.sub(r"\s*[^\w\s\sáéíóúñÁÉÍÓÚÑ]+\s*$", "", texto)

        return " ".join(texto.split()).strip()

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
