"""
enriquecedor_web.py
Búsqueda web automática para completar datos faltantes de bicicletas
cuando el scraping de detalle no los tiene.
Usa DuckDuckGo HTML (sin API key).
Solo se usa como fallback para campos críticos: peso, suspensión trasera, año, km.
"""

import re
import requests
from bs4 import BeautifulSoup
from models import Bicicleta


def _buscar_duckduckgo(consulta: str) -> str:
    """Hace una búsqueda en DuckDuckGo HTML y devuelve el HTML de resultados."""
    url = "https://html.duckduckgo.com/html/"
    try:
        resp = requests.post(url, data={"q": consulta}, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        }, timeout=20)
        if resp.status_code == 200:
            return resp.text
    except Exception:
        pass
    return ""


def _extraer_peso(texto: str):
    """Extrae peso en kg de un texto. Devuelve float o None."""
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*kg\b", texto, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1).replace(",", "."))
        except ValueError:
            pass
    return None


def _extraer_ano(texto: str):
    """Extrae año de un texto. Devuelve int o None."""
    match = re.search(r"\b(20\d{2})\b", texto)
    if match:
        return int(match.group(1))
    return None


def _detectar_suspension_trasera(texto: str):
    """
    Detecta si el texto indica suspensión trasera (doble suspensión).
    Devuelve True si sí tiene, False si claramente no, None si no se puede saber.
    """
    texto_lower = texto.lower()
    negativos = ["no tiene suspensión trasera", "sin amortiguador", "solo horquilla",
                 "hardtail", "rigid", "sin suspensión trasera", "no amortiguador"]
    if any(k in texto_lower for k in negativos):
        return False
    positivos = ["amortiguador", "suspensión trasera", "doble suspensión",
                 "full suspension", "full-suspension", "suspension trasera"]
    if any(k in texto_lower for k in positivos):
        return True
    return None


def enriquecer_bici(bici: Bicicleta) -> Bicicleta:
    """
    Intenta completar datos faltantes de una bici mediante búsqueda web.
    Solo busca los campos que faltan: peso_kg, suspension_trasera, ano, km.
    Devuelve la bici con los campos que se lograron completar.
    """
    faltan_peso = bici.peso_kg is None
    faltan_suspension = bici.suspension_trasera is None
    faltan_ano = bici.ano is None

    if not (faltan_peso or faltan_suspension or faltan_ano):
        return bici

    consulta = f"{bici.sitio} {bici.titulo} especificaciones peso kg"
    html = _buscar_duckduckgo(consulta)
    if not html:
        return bici

    soup = BeautifulSoup(html, "html.parser")
    fragmentos = []
    for res in soup.select(".result")[:5]:
        titulo_el = res.select_one(".result__a")
        snippet_el = res.select_one(".result__snippet")
        texto = ""
        if titulo_el:
            texto += titulo_el.get_text(" ", strip=True) + " "
        if snippet_el:
            texto += snippet_el.get_text(" ", strip=True) + " "
        fragmentos.append(texto)

    texto_completo = " ".join(fragmentos)

    if faltan_peso:
        peso = _extraer_peso(texto_completo)
        if peso is not None:
            bici.peso_kg = peso

    if faltan_ano:
        ano = _extraer_ano(texto_completo)
        if ano is not None:
            bici.ano = ano

    if faltan_suspension:
        susp = _detectar_suspension_trasera(texto_completo)
        if susp is True:
            bici.suspension_trasera = "detectada por búsqueda web"

    return bici