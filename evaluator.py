"""
evaluator.py
Filtros estrictos (S1-S6, S8) y algoritmo de "Nota de Oportunidad" 0-10 (S7).

Cada bicicleta que pase los filtros estrictos recibe una nota del 0 al 10.
Solo las que obtengan >= 8.0 se guardan y notifican (S8).
"""

import re
from typing import Tuple, List, Optional
from models import Bicicleta
import config as cfg

TECHO_NOTA_BH: float = 8.5


def es_bici_bh(bici: Bicicleta) -> bool:
    """Detecta si la bicicleta pertenece a la marca BH (centralita cerrada sin informe pericial PDF)."""
    texto = f"{bici.titulo or ''} {bici.motor or ''}".lower()
    if any(k in texto for k in ("ilynx", "atomx", "xtep", "2exmag", "2esmag")):
        return True
    return bool(re.search(r"\bbh\b", texto))


# ---------------------------------------------------------------------------
# FILTROS ESTRICTOS
# ---------------------------------------------------------------------------

def _pasa_requisitos_base_mecanicos(
    bici: Bicicleta,
    precio_max: int,
    bateria_estricta_gt: bool = True,
) -> Tuple[bool, str]:
    """
    Valida compatibilidad física y de presupuesto base compartida entre el flujo
    diario (S0-S6) y el canal exclusivo Black Friday.
    """
    # S0: Disponibilidad real (no reservada ni agotada)
    if getattr(bici, "disponible", True) is False:
        return False, "Bicicleta reservada o agotada"

    # S1: Talla exclusivamente M
    if bici.talla and bici.talla.strip().upper() != cfg.TALLA_OBJETIVO.upper():
        return False, f"Talla no es M: {bici.talla}"

    # S2: Modalidad XC / Downcountry / Light e-MTB
    if bici.modalidad:
        modalidad = bici.modalidad.strip().lower()
        if not any(m.lower() in modalidad for m in cfg.MODALIDADES_VALIDAS):
            return False, f"Modalidad no válida: {bici.modalidad}"

    # S4: Batería > 500 Wh en flujo diario, o >= 500 Wh en Black Friday
    if bici.bateria_wh is not None:
        if bateria_estricta_gt and bici.bateria_wh <= cfg.BATERIA_MIN_WH:
            return False, f"Batería <= 500 Wh: {bici.bateria_wh} Wh"
        if not bateria_estricta_gt and bici.bateria_wh < cfg.BATERIA_MIN_WH:
            return False, f"Batería < 500 Wh: {bici.bateria_wh} Wh"

    # S3: Peso >= 21 kg se descarta explícitamente (objetivo: estrictamente < 21 kg)
    if bici.peso_kg is not None and bici.peso_kg >= cfg.PESO_DESCARTE_KG:
        return False, f"Peso >= 21 kg: {bici.peso_kg} kg"

    # S3bis: Doble suspensión obligatoria.
    if bici.suspension_trasera is not None and str(bici.suspension_trasera).lower() in ("false", "no", "0"):
        return False, "No tiene suspensión trasera (no es doble suspensión)"

    # S2bis: Si el recorrido de suspensión supera 170 mm, se descarta por Enduro/Freeride
    if bici.recorrido_mm is not None and bici.recorrido_mm > 170:
        return False, f"Recorrido de suspensión excesivo para Light e-MTB / XC: {bici.recorrido_mm} mm"

    # S5/S6: Rango de presupuesto según canal
    if bici.precio < cfg.PRECIO_MIN_EUR:
        return False, f"Precio < {cfg.PRECIO_MIN_EUR} €: {bici.precio} €"
    if bici.precio > precio_max:
        return False, f"Precio > {precio_max} €: {bici.precio} €"

    return True, "OK"


def pasa_filtros_estrictos(bici: Bicicleta) -> Tuple[bool, str]:
    """
    Devuelve (apto, motivo) aplicando todos los filtros estrictos.
    Motivo explica por qué se descarta, si corresponde.
    """
    return _pasa_requisitos_base_mecanicos(
        bici,
        precio_max=cfg.PRECIO_MAX_EXCEPCIONAL_EUR,
        bateria_estricta_gt=True,
    )


def prioridad_modalidad(bici: Bicicleta) -> int:
    """
    Devuelve el nivel de prioridad de la modalidad para priorizar siempre XC frente a Trail:
      3 -> XC / Cross Country / Downcountry (<= 130 mm, ej. BH iLynx Race, Scott Lumen, KTM Scarp)
      2 -> Light e-MTB / Trail ligero (131-145 mm, ej. Orbea Rise, Trek Fuel EXe, BH iLynx Trail sin '+')
      1 -> Trail / All Mountain general (146-165 mm, ej. BH iLynx+ Trail)
      0 -> Otras / sin clasificar (> 165 mm / Enduro)
    """
    # 1. Prioridad objetiva por recorrido físico de suspensión si se conoce (TODO 2)
    if bici.recorrido_mm is not None:
        rec = bici.recorrido_mm
        if rec <= 130:
            return 3
        elif rec <= 145:
            return 2
        elif rec <= 165:
            return 1
        else:
            return 0

    # 2. Heurística semántica por título / modelo / modalidad cuando no hay recorrido explícito
    titulo = (bici.titulo or "").lower()
    modalidad = (bici.modalidad or "").lower()
    texto = f"{titulo} {modalidad}"

    # Nivel 3: XC / Cross Country / Downcountry puro
    if any(
        k in texto
        for k in (
            "ilynx race",
            "scott lumen",
            "macina scarp",
            "ams hybrid one44",
            "e-caliber",
            "downcountry",
            "cross country",
        )
    ) or "xc" in modalidad.split():
        return 3
    if "xc" in modalidad:
        return 3

    # Nivel 2: Light e-MTB / Trail ligero (excluyendo iLynx+ de 160 mm)
    if "ilynx+" not in titulo and "ilynx plus" not in titulo:
        if any(
            k in texto
            for k in (
                "orbea rise",
                "fuel exe",
                "levo sl",
                "ilynx trail",
                "e-zesty",
                "ezesty",
                "vam2 sl",
                "jam2 sl",
                "mondraker neat",
                "moterra sl",
                "light e-mtb",
                "light emtb",
            )
        ):
            return 2

    # Nivel 1: Trail / All Mountain
    if any(k in texto for k in ("trail", "all mountain")):
        return 1

    return 0


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
    if getattr(bici, "range_extender_wh", None):
        puntos += 0.5
        partes.append(f"Range Extender {bici.range_extender_wh}Wh incluido: +0.5")
    pvp_orig = getattr(bici, "pvp_original", None)
    if pvp_orig and pvp_orig > bici.precio > 0:
        pct_dto = (pvp_orig - bici.precio) / pvp_orig
        if pct_dto >= 0.50:
            puntos += 0.5
            partes.append(f"Mega Chollo ({pct_dto*100:.0f}% dto vs PVP): +0.5")

    if bici.precio <= cfg.PRECIO_MAX_EUR:
        puntos += 0.5
        partes.append("precio en rango principal: +0.5")

    return min(puntos, 3.0), "; ".join(partes) if partes else "Componentes estándar"


def _puntuacion_motor(bici: Bicicleta) -> Tuple[float, str]:
    """
    Desgaste de motor: mayor puntuación si marca con diagnóstico claro
    (Shimano EP8/EP801, Bosch) o muy pocos kilómetros.
    Las bicicletas BH pierden la bonificación de diagnóstico transparente por usar
    centralita propietaria sin informe PDF oficial verificable.
    Devuelve (puntos 0-2.5, justificación).
    """
    texto = f"{bici.motor or ''} {bici.titulo or ''}".lower()
    es_bh = es_bici_bh(bici)
    puntos = 0.0
    partes: List[str] = []

    if es_bh:
        if any(m.lower() in texto for m in cfg.MOTORES_LIGEROS):
            puntos += 0.5
            partes.append("motor ligero BH sin informe PDF oficial: +0.5")
        else:
            partes.append("centralita BH sin informe pericial oficial: +0.0")
    elif any(m.lower() in texto for m in cfg.MOTORES_LIGEROS):
        puntos += 1.5
        partes.append("motor ligero/diagnóstico claro: +1.5")

    if bici.km is not None and bici.km < 1000:
        puntos += 1.0
        partes.append("pocos km en motor: +1.0")
    salud_bat = getattr(bici, "bateria_salud_pct", None)
    if salud_bat is not None:
        if salud_bat >= 92:
            puntos += 0.5
            partes.append(f"salud batería certificada ({salud_bat}%): +0.5")
        elif salud_bat < 85:
            puntos = max(0.0, puntos - 1.0)
            partes.append(f"salud batería degradada ({salud_bat}%): -1.0")

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
    Aplica deducción preventiva (-1.0 pt) y techo (máx 8.5) a bicis BH
    por carecer de informe pericial verificable de desgaste y batería.
    Total máximo: 10.0
    """
    p_km, j_km = _puntuacion_km(bici.km)
    p_cp, j_cp = _puntuacion_calidad_precio(bici)
    p_motor, j_motor = _puntuacion_motor(bici)
    p_precio, j_precio = _puntuacion_precio_excepcional(bici)

    nota = p_km + p_cp + p_motor + p_precio
    sufijo_bh = ""
    if es_bici_bh(bici):
        nota = min(nota - 1.0, TECHO_NOTA_BH)
        sufijo_bh = f" | Ajuste BH (sin informe pericial PDF): -1.0 (máx {TECHO_NOTA_BH})"

    nota = round(max(0.0, min(10.0, nota)), 2)

    desglose = (
        f"Kilometraje: {j_km} | "
        f"Calidad-precio: {j_cp} | "
        f"Motor: {j_motor} | "
        f"Precio: {j_precio}{sufijo_bh}"
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


# ---------------------------------------------------------------------------
# CANAL EXCLUSIVO BLACK FRIDAY (NUEVAS / EXPOSICIÓN <= 3.500 €)
# ---------------------------------------------------------------------------

_RE_RECLAMO_NUEVA = re.compile(
    r"\b(?:nueva|a\s+estrenar|sin\s+usar|precintad[oa]|km\.?\s*0|exposici[oó]n)\b",
    re.IGNORECASE,
)


def calcular_descuento_pvp_pct(bici: Bicicleta) -> Optional[float]:
    """Calcula el % de descuento real frente a pvp_original, o None si no hay PVP válido."""
    pvp_orig = getattr(bici, "pvp_original", None)
    precio = getattr(bici, "precio", None)
    if not pvp_orig or pvp_orig <= 0 or not precio or precio <= 0 or pvp_orig <= precio:
        return None
    return round(((pvp_orig - precio) / pvp_orig) * 100.0, 1)


def clasificar_estado_nueva_exposicion(bici: Bicicleta) -> Tuple[bool, str, str]:
    """
    Verifica con escepticismo si la bicicleta es realmente nueva o de exposición (km <= 50)
    sin contradicciones de anuncio ni kilometrajes desconocidos.
    """
    texto = f"{bici.titulo or ''} {bici.componentes or ''}"
    km = bici.km

    if km is not None and km > cfg.KM_MAX_BLACK_FRIDAY:
        if _RE_RECLAMO_NUEVA.search(texto):
            return False, "CONTRADICCIÓN", f"Reclamo de nueva/exposición contradictorio con {km} km"
        return False, "USADA", f"Kilometraje > {cfg.KM_MAX_BLACK_FRIDAY} km ({km} km)"

    if km is None:
        return False, "KM_NO_CONFIRMADO", "Kilometraje no especificado para garantizar estado nuevo/exposición"

    sitio_lower = (bici.sitio or "").lower()
    url_lower = (bici.url or "").lower()
    es_tienda_nueva = (
        sitio_lower == "mammoth"
        or (sitio_lower == "buhobike" and "segunda-mano" not in url_lower and "segunda mano" not in texto.lower())
    )
    if km == 0 and es_tienda_nueva:
        return True, "NUEVA (0 km)", "Tienda oficial con 0 km confirmados"
    if km == 0:
        return True, "A ESTRENAR / KM 0 (0 km)", "0 km confirmados"
    return True, f"EXPOSICIÓN / KM 0 ({km} km)", f"Unidad de exposición/test con {km} km"


def pasa_prefiltro_black_friday(bici: Bicicleta) -> Tuple[bool, str]:
    """
    Pre-filtro previo al enriquecimiento para rescatar bicis nuevas/exposición
    de 2.000-3.500 € (incluyendo la franja 3.301-3.500 € del Black Friday).
    """
    apto_base, motivo_base = _pasa_requisitos_base_mecanicos(
        bici,
        precio_max=cfg.PRECIO_MAX_BLACK_FRIDAY_EUR,
        bateria_estricta_gt=False,
    )
    if not apto_base:
        return False, motivo_base

    es_nueva, _, motivo_estado = clasificar_estado_nueva_exposicion(bici)
    if not es_nueva:
        return False, motivo_estado
    return True, "OK"


def _puntuacion_black_friday(
    bici: Bicicleta,
    descuento_pct: float,
    etiqueta_estado: str,
) -> Tuple[float, str]:
    """
    Rúbrica específica de oportunidad Black Friday (0.0 a 10.0) sobre unidades
    nuevas o de exposición (< 21 kg, Talla M, >= 500 Wh, <= 3.500 €).
    """
    # 1. Descuento real frente a PVP (hasta 4.0 pts)
    if descuento_pct >= 55.0:
        p_dto = 4.0
    elif descuento_pct >= 45.0:
        p_dto = 3.5
    elif descuento_pct >= 40.0:
        p_dto = 3.0
    else:
        p_dto = 2.5

    # 2. Peso real verificado < 21.0 kg (hasta 2.5 pts)
    peso = float(bici.peso_kg)
    if peso <= 19.0:
        p_peso = 2.5
    elif peso <= 19.8:
        p_peso = 2.0
    elif peso <= 20.5:
        p_peso = 1.5
    else:
        p_peso = 1.0

    # 3. Estado nuevo / exposición (hasta 1.5 pts)
    km = int(bici.km or 0)
    if km == 0:
        p_estado = 1.5
    elif km <= 15:
        p_estado = 1.3
    else:
        p_estado = 1.0

    # 4. Garantía y canal (hasta 1.0 pt)
    sitio_lower = (bici.sitio or "").lower()
    garantia = bici.garantia_anos if bici.garantia_anos is not None else 0
    if sitio_lower == "wallapop":
        p_gar = 0.4 if getattr(bici, "tiene_factura", False) else 0.1
    elif garantia >= 2:
        p_gar = 1.0
    elif garantia >= 1:
        p_gar = 0.8
    else:
        p_gar = 0.4

    # 5. Montaje, auditoría de motor y banda de presupuesto (hasta 1.0 pt)
    comp = (bici.componentes or "").lower()
    cuadro = (bici.cuadro_material or "").lower()
    motor_str = (bici.motor or "").lower()
    es_gama_alta = any(k in comp for k in ("xtr", "xx1", "x01", "axs", "xt", "gx", "kashima", "factory", "ultimate"))
    es_carbono = any(k in f"{cuadro} {bici.titulo or ''}".lower() for k in ("carbon", "carbono"))
    p_comp = 1.0 if (es_gama_alta or es_carbono) else 0.6

    notas_extra: List[str] = []
    if "2exmag" in motor_str or (es_bici_bh(bici) and "ilynx+" not in (bici.titulo or "").lower()):
        p_comp -= 0.5
        notas_extra.append("motor cerrado BH 2EXMAG (-0.5)")
    elif "bosch" in motor_str and "sx" not in motor_str and "pdf" not in comp:
        p_comp -= 0.3
        notas_extra.append("Bosch sin informe PDF (-0.3)")

    if bici.precio > cfg.PRECIO_MAX_EXCEPCIONAL_EUR:
        p_comp -= 0.3
        notas_extra.append("tramo tope 3.301-3.500 € (-0.3)")

    nota_bf = round(max(0.0, min(10.0, p_dto + p_peso + p_estado + p_gar + p_comp)), 2)
    extra_txt = f" | Matices: {', '.join(notas_extra)}" if notas_extra else ""
    desglose = (
        f"Dto PVP -{descuento_pct:.1f}% (+{p_dto:.1f}) | "
        f"Peso {peso:.1f} kg (+{p_peso:.1f}) | "
        f"{etiqueta_estado} (+{p_estado:.1f}) | "
        f"Garantía (+{p_gar:.1f}) | "
        f"Montaje (+{p_comp:.1f}){extra_txt}"
    )
    return nota_bf, desglose


def evaluar_oportunidad_black_friday(
    bici: Bicicleta,
    nota_perito: Optional[float] = None,
) -> Tuple[bool, float, Optional[float], str, str]:
    """
    Evalúa post-enriquecimiento si una bicicleta califica como oportunidad super
    exclusiva de Black Friday para el segundo chat de Telegram.
    Devuelve (califica, nota_bf, descuento_pct, etiqueta_estado, desglose).
    """
    apto_base, motivo_base = _pasa_requisitos_base_mecanicos(
        bici,
        precio_max=cfg.PRECIO_MAX_BLACK_FRIDAY_EUR,
        bateria_estricta_gt=False,
    )
    if not apto_base:
        return False, 0.0, None, "DESCARTADA", motivo_base

    # Guardas estrictas de completitud para evitar falsos positivos con datos ausentes
    if not bici.talla or bici.talla.strip().upper() != cfg.TALLA_OBJETIVO.upper():
        return False, 0.0, None, "DESCARTADA", f"Talla no confirmada como M ({bici.talla})"
    if str(bici.suspension_trasera or "").strip().lower() not in ("si", "sí", "true", "1"):
        return False, 0.0, None, "DESCARTADA", f"Doble suspensión no confirmada ({bici.suspension_trasera})"
    if getattr(bici, "_peso_estimado", False):
        return False, 0.0, None, "DESCARTADA", f"Peso estimado por heurística/IA sin verificación real ({bici.peso_kg} kg)"
    if bici.peso_kg is None or bici.peso_kg >= cfg.PESO_DESCARTE_KG:
        return False, 0.0, None, "DESCARTADA", f"Peso real no confirmado < 21.0 kg ({bici.peso_kg})"
    if bici.bateria_wh is None or bici.bateria_wh < cfg.BATERIA_MIN_WH:
        return False, 0.0, None, "DESCARTADA", f"Batería no confirmada >= 500 Wh ({bici.bateria_wh})"

    es_nueva, etiqueta_estado, motivo_estado = clasificar_estado_nueva_exposicion(bici)
    if not es_nueva:
        return False, 0.0, None, etiqueta_estado, motivo_estado

    descuento_pct = calcular_descuento_pvp_pct(bici)
    if descuento_pct is None:
        return False, 0.0, None, "SIN_PVP", "Sin PVP original verificable para acreditar chollo exclusivo"
    if descuento_pct < cfg.DESCUENTO_MIN_BLACK_FRIDAY_PCT:
        return (
            False,
            0.0,
            descuento_pct,
            "DTO_INSUFICIENTE",
            f"Descuento -{descuento_pct:.1f}% < mínimo exclusivo -{cfg.DESCUENTO_MIN_BLACK_FRIDAY_PCT:.0f}%",
        )

    nota_bf, desglose_bf = _puntuacion_black_friday(bici, descuento_pct, etiqueta_estado)
    if nota_bf < cfg.NOTA_MIN_BLACK_FRIDAY:
        return (
            False,
            nota_bf,
            descuento_pct,
            "NOTA_INSUFICIENTE",
            f"Nota BF {nota_bf}/10 < {cfg.NOTA_MIN_BLACK_FRIDAY}: {desglose_bf}",
        )

    return True, nota_bf, descuento_pct, etiqueta_estado, desglose_bf


def pasa_prefiltro_respaldo_black_friday(bici: Bicicleta) -> Tuple[bool, str]:
    """
    Pre-filtro amplio previo al enriquecimiento para localizar el Top 3 más
    interesante aunque supere 3.500 € o tenga batería >= 450 Wh (ej. Fazua 480 Wh).
    """
    if getattr(bici, "disponible", True) is False:
        return False, "Bicicleta reservada o agotada"
    if bici.talla and bici.talla.strip().upper() != cfg.TALLA_OBJETIVO.upper():
        return False, f"Talla no es M: {bici.talla}"
    if bici.modalidad:
        modalidad = bici.modalidad.strip().lower()
        if not any(m.lower() in modalidad for m in cfg.MODALIDADES_VALIDAS):
            return False, f"Modalidad no válida: {bici.modalidad}"
    if bici.suspension_trasera is not None and str(bici.suspension_trasera).lower() in ("false", "no", "0"):
        return False, "No tiene suspensión trasera"
    if bici.recorrido_mm is not None and bici.recorrido_mm > 170:
        return False, f"Recorrido > 170 mm: {bici.recorrido_mm} mm"
    if bici.bateria_wh is not None and bici.bateria_wh < 450:
        return False, f"Batería < 450 Wh: {bici.bateria_wh} Wh"
    if bici.peso_kg is not None and bici.peso_kg >= cfg.PESO_DESCARTE_KG:
        return False, f"Peso >= 21 kg: {bici.peso_kg} kg"
    if bici.precio < cfg.PRECIO_MIN_EUR:
        return False, f"Precio < {cfg.PRECIO_MIN_EUR} €"
    if bici.precio <= cfg.PRECIO_MAX_EXCEPCIONAL_EUR and (bici.km is None or bici.km > cfg.KM_MAX_BLACK_FRIDAY):
        return False, "Solo rescata <= 3.300 € con km <= 50 o precios > 3.300 €"
    return True, "OK"


def evaluar_respaldo_black_friday(
    bici: Bicicleta,
    nota_perito: Optional[float] = None,
) -> Tuple[bool, Optional[float], float, str, tuple]:
    """
    Evalúa alternativas ligeras (< 21.0 kg, Talla M, doble, km <= 1.500, >= 450 Wh,
    dto >= 25% PVP) para el informe de respaldo cuando 0 bicis pasan el tope de 3.500 €.
    Devuelve (califica, dto_pct, nota_ref, motivo_fuera, clave_orden).
    """
    if getattr(bici, "disponible", True) is False:
        return False, None, 0.0, "No disponible", ()
    if not bici.talla or bici.talla.strip().upper() != cfg.TALLA_OBJETIVO.upper():
        return False, None, 0.0, "Talla no M", ()
    if str(bici.suspension_trasera or "").strip().lower() not in ("si", "sí", "true", "1"):
        return False, None, 0.0, "Doble suspensión no confirmada", ()
    if bici.recorrido_mm is not None and bici.recorrido_mm > 170:
        return False, None, 0.0, "Recorrido > 170 mm", ()
    if bici.peso_kg is None or bici.peso_kg >= cfg.PESO_DESCARTE_KG:
        return False, None, 0.0, "Peso >= 21 kg o desconocido", ()
    if bici.bateria_wh is None or bici.bateria_wh < 450:
        return False, None, 0.0, "Batería < 450 Wh", ()
    if bici.km is None or bici.km > 1500:
        return False, None, 0.0, "Kilometraje > 1.500 km o no confirmado", ()
    if bici.precio < cfg.PRECIO_MIN_EUR:
        return False, None, 0.0, "Precio < mínimo", ()

    dto_pct = calcular_descuento_pvp_pct(bici)
    if dto_pct is None or dto_pct < 25.0:
        return False, dto_pct, 0.0, "Descuento < 25% o sin PVP", ()

    razones: List[str] = []
    if bici.precio > cfg.PRECIO_MAX_BLACK_FRIDAY_EUR:
        razones.append(f"+{bici.precio - cfg.PRECIO_MAX_BLACK_FRIDAY_EUR:.0f} € sobre tope 3.500 €")
    if bici.km > cfg.KM_MAX_BLACK_FRIDAY:
        razones.append(f"{bici.km} km (seminueva)")
    if bici.bateria_wh < cfg.BATERIA_MIN_WH:
        razones.append(f"batería {bici.bateria_wh} Wh (< 500 Wh)")
    if dto_pct < cfg.DESCUENTO_MIN_BLACK_FRIDAY_PCT:
        razones.append(f"dto -{dto_pct:.0f}% (< 35%)")
    if getattr(bici, "_peso_estimado", False):
        razones.append("peso est. sin báscula")

    motivo_fuera = " | ".join(razones) if razones else "Alternativa cercana"
    cumple_salvo_precio = (
        bici.bateria_wh >= cfg.BATERIA_MIN_WH
        and bici.km <= cfg.KM_MAX_BLACK_FRIDAY
        and dto_pct >= cfg.DESCUENTO_MIN_BLACK_FRIDAY_PCT
        and not getattr(bici, "_peso_estimado", False)
    )
    clave_orden = (
        1 if cumple_salvo_precio else 0,
        1 if bici.bateria_wh >= cfg.BATERIA_MIN_WH else 0,
        1 if bici.km <= cfg.KM_MAX_BLACK_FRIDAY else 0,
        round(dto_pct, 1),
        -(bici.peso_kg or 21.0),
        -float(bici.precio),
    )
    nota_ref = round(nota_perito if nota_perito is not None else 0.0, 2)
    return True, dto_pct, nota_ref, motivo_fuera, clave_orden
