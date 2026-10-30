"""
evaluator.py
Filtros estrictos (S1-S6, S8) y algoritmo de "Nota de Oportunidad" 0-10 (S7).

Cada bicicleta que pase los filtros estrictos recibe una nota del 0 al 10.
Solo las que obtengan >= 8.0 se guardan y notifican (S8).
"""

from typing import Tuple, List
from models import Bicicleta
import config as cfg


# ---------------------------------------------------------------------------
# FILTROS ESTRICTOS
# ---------------------------------------------------------------------------

def pasa_filtros_estrictos(bici: Bicicleta) -> Tuple[bool, str]:
    """
    Devuelve (apto, motivo) aplicando todos los filtros estrictos.
    Motivo explica por qué se descarta, si corresponde.
    """
    # S1: Talla exclusivamente M
    if bici.talla and bici.talla.strip().upper() != cfg.TALLA_OBJETIVO.upper():
        return False, f"Talla no es M: {bici.talla}"

    # S2: Modalidad XC / Downcountry / Light e-MTB
    if bici.modalidad:
        modalidad = bici.modalidad.strip().lower()
        if not any(m.lower() in modalidad for m in cfg.MODALIDADES_VALIDAS):
            return False, f"Modalidad no válida: {bici.modalidad}"

    # S4: Batería estrictamente > 500 Wh
    if bici.bateria_wh is not None and bici.bateria_wh <= cfg.BATERIA_MIN_WH:
        return False, f"Batería <= 500 Wh: {bici.bateria_wh} Wh"

    # S3: Peso > 21 kg se descarta explícitamente
    if bici.peso_kg is not None and bici.peso_kg > cfg.PESO_DESCARTE_KG:
        return False, f"Peso > 21 kg: {bici.peso_kg} kg"

    # S5/S6: Precio entre 2.000 € y 3.300 € (excepcional hasta 3.300 €)
    if bici.precio < cfg.PRECIO_MIN_EUR:
        return False, f"Precio < 2.000 €: {bici.precio} €"
    if bici.precio > cfg.PRECIO_MAX_EXCEPCIONAL_EUR:
        return False, f"Precio > 3.300 €: {bici.precio} €"

    return True, "OK"


# ---------------------------------------------------------------------------
# ALGORITMO DE NOTA DE OPORTUNIDAD (0-10) (S7)
# ---------------------------------------------------------------------------

def _puntuacion_km(km) -> Tuple[float, str]:
    """
    Kilometraje: penaliza fuertemente > 4.000 km, premia < 2.000 km.
    Devuelve (puntos 0-2.5, justificación).
    """
    if km is None:
        return 1.0, "Kilometraje desconocido (neutro)"
    if km < 2000:
        return 2.5, f"Km bajos ({km} km): +2.5"
    if km <= 4000:
        return 1.5, f"Km moderados ({km} km): +1.5"
    return 0.5, f"Km altos ({km} km): +0.5"


def _puntuacion_calidad_precio(bici: Bicicleta) -> Tuple[float, str]:
    """
    Relación calidad-precio: compara precio frente a componentes (XT/AXS,
    suspensiones Kashima/Ultimate, cuadro de carbono).
    Devuelve (puntos 0-3.0, justificación).
    """
    texto = f"{bici.titulo} {bici.componentes or ''}".lower()
    puntos = 0.0
    partes: List[str] = []

    if any(m in texto for m in cfg.MATERIALES_CUADRO_LIGERO):
        puntos += 1.0
        partes.append("cuadro carbono: +1.0")
    if any(m in texto for m in ["xt", "axs", "x0", "xtr"]):
        puntos += 1.0
        partes.append("transmisión tope (XT/AXS): +1.0")
    if any(m in texto for m in ["kashima", "ultimate", "factory"]):
        puntos += 1.0
        partes.append("suspensión premium (Kashima/Ultimate): +1.0")

    if bici.precio <= cfg.PRECIO_MAX_EUR:
        puntos += 0.5
        partes.append("precio en rango principal: +0.5")

    return min(puntos, 3.0), "; ".join(partes) if partes else "Componentes estándar"


def _puntuacion_motor(bici: Bicicleta) -> Tuple[float, str]:
    """
    Desgaste de motor: mayor puntuación si marca con diagnóstico claro
    (Shimano EP8/EP801) o muy pocos kilómetros.
    Devuelve (puntos 0-2.5, justificación).
    """
    texto = f"{bici.motor or ''} {bici.titulo or ''}".lower()
    puntos = 0.0
    partes: List[str] = []

    if any(m.lower() in texto for m in cfg.MOTORES_LIGEROS):
        puntos += 1.5
        partes.append("motor ligero/diagnóstico claro: +1.5")
    if bici.km is not None and bici.km < 1000:
        puntos += 1.0
        partes.append("pocos km en motor: +1.0")

    return min(puntos, 2.5), "; ".join(partes) if partes else "Motor estándar o desconocido"


def _puntuacion_precio_excepcional(bici: Bicicleta) -> Tuple[float, str]:
    """
    Oportunidad excepcional: precio muy competitivo para los componentes.
    Devuelve (puntos 0-2.0, justificación).
    """
    if bici.precio <= cfg.PRECIO_MAX_EUR:
        return 2.0, "Precio en rango principal 2.000-3.000 €: +2.0"
    if bici.precio <= cfg.PRECIO_MAX_EXCEPCIONAL_EUR:
        return 1.0, "Precio en rango excepcional hasta 3.300 €: +1.0"
    return 0.0, "Fuera de rango de precio"


def calcular_nota_oportunidad(bici: Bicicleta) -> Tuple[float, str]:
    """
    Calcula la nota de oportunidad (0-10) y devuelve (nota, desglose).
    Pesos:
      - Kilometraje:           2.5
      - Calidad-precio:        3.0
      - Motor / diagnóstico:   2.5
      - Precio excepcional:    2.0
    Total máximo: 10.0
    """
    p_km, j_km = _puntuacion_km(bici.km)
    p_cp, j_cp = _puntuacion_calidad_precio(bici)
    p_motor, j_motor = _puntuacion_motor(bici)
    p_precio, j_precio = _puntuacion_precio_excepcional(bici)

    nota = round(p_km + p_cp + p_motor + p_precio, 2)
    nota = max(0.0, min(10.0, nota))

    desglose = (
        f"Kilometraje: {j_km} | "
        f"Calidad-precio: {j_cp} | "
        f"Motor: {j_motor} | "
        f"Precio: {j_precio}"
    )
    return nota, desglose


def evaluar(bici: Bicicleta) -> Tuple[bool, float, str]:
    """
    Aplica filtros estrictos y, si pasa, calcula la nota.
    Devuelve (apto, nota, desglose).
    """
    apto, motivo = pasa_filtros_estrictos(bici)
    if not apto:
        return False, 0.0, motivo
    nota, desglose = calcular_nota_oportunidad(bici)
    if nota < cfg.NOTA_MIN_AGUARDAR:
        return False, nota, f"Nota {nota} < {cfg.NOTA_MIN_AGUARDAR}: {desglose}"
    return True, nota, desglose
