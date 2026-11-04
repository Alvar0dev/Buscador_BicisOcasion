"""
scrapers/upway.py
Adaptador para Upway (upway.es).
Selectores CSS ajustados tras inspección real de la web (S14, S11).
Categoría objetivo: bicicletas eléctricas de montaña doble suspensión (/collections/doble-suspension).

Estructura observada en upway.es:
  <a class="w-full" href="/products/moustache-samedi-29-trail-3-rk7fu0">
    Más vendida Moustache Samedi 29 Trail 3 2023 1m69-1m85 10.152 km 1.999 € 5.499 € nuevo
  </a>
"""

from typing import List, Optional
from bs4 import BeautifulSoup
from models import Bicicleta
from scraper_base import BaseScraper
import config as cfg
import re


class UpwayScraper(BaseScraper):
    def extraer_bicicletas(self) -> List[Bicicleta]:
        soup = self.sopa(self.sitio.seccion_emtb)
        if soup is None:
            return []
        return self._extraer_de_sopa(soup)

    def _extraer_de_sopa(self, soup: BeautifulSoup) -> List[Bicicleta]:
        bicis: List[Bicicleta] = []
        # Selectores reales observados en upway.es:
        # Enlaces a producto: <a class="w-full" href="/products/<slug>-<id>">
        productos = soup.select('a.w-full[href*="/products/"]')
        es_coleccion_doble = "doble-suspension" in self.sitio.seccion_emtb.lower()

        for p in productos:
            try:
                href = p.get("href", "")
                if not href:
                    continue

                url = self.url_absoluta(href)

                # bici_id: último segmento del slug (ej. "rk7fu0")
                slug = href.rstrip("/").split("/")[-1]
                bici_id = slug.split("-")[-1] if slug else slug

                # Texto del enlace con espacios entre elementos hijos
                texto_completo = p.get_text(" ", strip=True)
                texto_completo = self.limpiar_texto(texto_completo) or ""
                titulo = self._extraer_titulo_simple(texto_completo)

                # Precio: primer valor en € encontrado en el texto
                precio = self._parsear_precio(texto_completo)

                if not titulo or precio <= 0:
                    continue

                # Extraer año, kilometraje y talla directamente del texto de la tarjeta
                # sin lanzar peticiones secuenciales bloqueantes (main.py ya enriquece
                # en paralelo con caché en disco solo las candidatas que pasan el pre-filtro).
                datos_tarjeta = self._extraer_datos_tarjeta(texto_completo)

                bicis.append(Bicicleta(
                    sitio=self.sitio.nombre,
                    bici_id=bici_id,
                    titulo=titulo,
                    precio=precio,
                    url=url,
                    talla=datos_tarjeta.get("talla"),
                    km=datos_tarjeta.get("km"),
                    ano=datos_tarjeta.get("ano"),
                    suspension_trasera="si" if es_coleccion_doble else datos_tarjeta.get("suspension_trasera"),
                    garantia_anos=self.sitio.garantia_anos,
                ))
            except Exception as e:
                print(f"[Upway] Error parseando producto: {e}")
                continue

        return bicis

    def _extraer_datos_tarjeta(self, texto: str) -> dict:
        """
        Extrae año, kilometraje y talla (a partir del rango de estatura '1mXX-1mYY')
        directamente del texto de la tarjeta del listado de Upway.
        Ejemplo:
          'Mejor precio Recién llegada Focus THRON² 6.9 2023 1m60-1m70 1786\u202fkm 2.499 € 6.000 € nuevo'
        """
        datos: dict = {}
        texto_norm = texto.replace("\u202f", " ").replace("\u00a0", " ")

        # 1. Año (4 dígitos entre 2015 y 2030, normalmente antes del rango de altura 1mXX-1mYY)
        match_ano = re.search(r"\b(20[12]\d)\b(?=\s+\d+m\d+|\s+<|\s+[\d.,]+\s*km)", texto_norm, re.IGNORECASE)
        if not match_ano:
            match_ano = re.search(r"\b(20[12]\d)\b", texto_norm)
        if match_ano:
            datos["ano"] = int(match_ano.group(1))

        # 2. Kilometraje ('< 5 km' -> 5, '10.152 km' -> 10152, '1786 km' -> 1786)
        match_km_menor = re.search(r"<\s*(\d+)\s*km\b", texto_norm, re.IGNORECASE)
        if match_km_menor:
            datos["km"] = int(match_km_menor.group(1))
        else:
            match_km = re.search(r"\b(\d[\d.,]*)\s*km\b", texto_norm, re.IGNORECASE)
            if match_km:
                km_str = match_km.group(1).replace(".", "").replace(",", "")
                if km_str.isdigit():
                    datos["km"] = int(km_str)

        # 3. Talla a partir del rango de altura '1mXX-1mYY' (ej. '1m68-1m81')
        match_altura = re.search(r"\b(\d)m(\d{2})\s*-\s*(\d)m(\d{2})\b", texto_norm, re.IGNORECASE)
        if match_altura:
            min_cm = int(match_altura.group(1)) * 100 + int(match_altura.group(2))
            max_cm = int(match_altura.group(3)) * 100 + int(match_altura.group(4))
            talla = self._inferir_talla_desde_altura(min_cm, max_cm)
            if talla:
                datos["talla"] = talla

        return datos

    @staticmethod
    def _inferir_talla_desde_altura(min_cm: int, max_cm: int) -> Optional[str]:
        """
        Convierte el rango de altura en cm de la tarjeta de Upway en talla estándar:
        - max_cm <= 163 -> XS
        - max_cm <= 172 -> S (ej. 1m55-1m70, 1m60-1m70)
        - min_cm >= 184 -> XL (ej. 1m85-1m95, 1m90-2m00)
        - min_cm >= 175 -> L (ej. 1m75-1m86, 1m78-1m88, 1m80-1m90)
        - min_cm <= 168 y 174 <= max_cm <= 183 -> M (ej. 1m63-1m76, 1m64-1m77, 1m65-1m80, 1m67-1m80, 1m68-1m81)
        - Rangos fronterizos (ej. 1m69-1m83 o 1m70-1m84, donde algunas marcas etiquetan M y otras L):
          devuelve None para que el enriquecedor paralelo verifique <dt>Talla</dt> en la ficha.
        """
        if max_cm <= 163:
            return "XS"
        if max_cm <= 172:
            return "S"
        if min_cm >= 184:
            return "XL"
        if min_cm >= 175:
            return "L"
        if min_cm <= 168 and 174 <= max_cm <= 183:
            return "M"
        return None

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

        # Eliminar precios al final (ej. "1.999 € 5.499 € nuevo" o "2.499 €")
        texto = re.sub(r"\s*[\d.,]+(?:\s*€)\s*[\d.,]*(?:\s*€)?\s*(?:nuevo|nueva)?\s*$", "", texto, flags=re.IGNORECASE)
        texto = re.sub(r"\s*(?:nuevo|nueva)\s*$", "", texto, flags=re.IGNORECASE)

        # Eliminar kilometraje (ej. "< 5 km", "10.152 km", "1786 km") sin comerse números de modelo previos (ej. "6.9")
        texto = re.sub(r"\s*(?:<\s*)?\d[\d.,]*\s*km\b\s*", " ", texto, flags=re.IGNORECASE)

        # Eliminar rangos de talla (ej. "1m64-1m77", "1m69-1m85", "1m80-1m93")
        texto = re.sub(r"\s*\d+m\d+-\d+m\d+\s*", " ", texto)

        # Eliminar años sueltos al final (ej. "2023")
        texto = re.sub(r"\s+20[12]\d\s*$", "", texto)

        # Eliminar caracteres sueltos de comparación o guiones al final (preservando '+' de modelos como 'Neo 4+')
        texto = re.sub(r"\s*[<>:\-]+\s*$", "", texto)

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
