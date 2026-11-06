"""
gemini_classifier.py
Clasificador y enriquecedor híbrido (Gemini Flash + Motor Autónomo Local sin API).

Responsabilidades:
  1. Completar campos técnicos faltantes de cada bicicleta (peso_kg, bateria_wh,
     motor, cuadro_material, suspension_trasera, modalidad, componentes, ano, km, talla)
     combinando:
       a) Ficha técnica de la tienda (Scrapling via enriquecedor_web)
       b) Catálogo técnico local de modelos e-MTB de referencia
       c) Gemini Flash (gemini-3.5-flash / gemini-3.5-flash-lite con Google Search)
  2. Evaluar la oportunidad de compra (nota 0.0 a 10.0 y análisis técnico)
     ponderando los 5 ejes clave:
       - Kilómetros y desgaste mecánico
       - Peso (< 21 kg excluyente, premiando <= 19 kg y cuadro de carbono)
       - Posibilidad de obtener documentación/diagnóstico fiable del motor
       - Estado y capacidad de la batería (> 500 Wh, degradación por km/año y garantía)
       - Componentes y relación calidad-precio dentro del rango 2.000-3.300 €
  3. Funcionar 100% autónomo sin API de Google si no hay GEMINI_API_KEY o si la cuota
     gratuita devuelve error/rate-limit.
"""

import json
import logging
import re
import threading
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests

import config as cfg
from models import Bicicleta
from scrapers.enriquecedor_web import enriquecer_bici, _buscar_en_cache

log = logging.getLogger("buscador.ia")

CACHE_DIR = cfg.BASE_DIR / "cache"
CACHE_IA_FILE = CACHE_DIR / "valoraciones_ia.json"
_CACHE_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Catálogo técnico de referencia e-MTB (para inferencia sin API y validación)
# ---------------------------------------------------------------------------
# Cada entrada define patrones de modelo y sus especificaciones reales de catálogo.
CATALOGO_EMTB = [
    {
        "patrones": ["bh ilynx race carbon", "ilynx race carbon"],
        "peso_kg": 16.8,
        "bateria_wh_default": 540,
        "motor": "BH 2EXMAG",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "XC / Downcountry",
    },
    {
        "patrones": ["bh ilynx+ trail carbon", "ilynx+ trail carbon", "bh ilynx+ enduro", "ilynx+"],
        "peso_kg": 20.4,
        "bateria_wh_default": 540,
        "motor": "Shimano EP801 (Sistema/Batería BH)",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail",
    },
    {
        "patrones": ["bh ilynx trail carbon", "ilynx trail carbon"],
        "peso_kg": 18.6,
        "bateria_wh_default": 540,
        "motor": "BH 2EXMAG",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Light e-MTB / Trail",
    },
    {
        "patrones": ["bh ilynx race"],
        "peso_kg": 18.9,
        "bateria_wh_default": 540,
        "motor": "BH 2EXMAG",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "XC / Downcountry",
    },
    {
        "patrones": ["bh ilynx trail"],
        "peso_kg": 19.6,
        "bateria_wh_default": 540,
        "motor": "BH 2EXMAG",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Light e-MTB / Trail",
    },
    {
        "patrones": ["orbea rise m", "orbea rise m10", "orbea rise m20", "orbea rise m-team", "orbea rise m-ltd"],
        "peso_kg": 18.3,
        "bateria_wh_default": 540,
        "motor": "Shimano EP801 RS",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Light e-MTB / Trail",
    },
    {
        "patrones": ["orbea rise h", "orbea rise h10", "orbea rise h15", "orbea rise h20", "orbea rise h30"],
        "peso_kg": 20.3,
        "bateria_wh_default": 540,
        "motor": "Shimano EP8 / EP6 RS",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Light e-MTB / Trail",
    },
    {
        "patrones": ["cannondale moterra sl"],
        "peso_kg": 19.5,
        "bateria_wh_default": 601,
        "motor": "Shimano EP801",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Light e-MTB / Trail",
    },
    {
        "patrones": ["specialized turbo levo sl", "levo sl"],
        "peso_kg": 17.9,
        "bateria_wh_default": 480,
        "motor": "Specialized SL 1.1 / 1.2",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Light e-MTB",
    },
    {
        "patrones": ["trek fuel+ ex 9", "fuel+ ex 9"],
        "peso_kg": 19.3,
        "bateria_wh_default": 580,
        "motor": "TQ HPR60",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Light e-MTB",
    },
    {
        "patrones": ["trek fuel+ ex", "fuel+ ex"],
        "peso_kg": 21.08,
        "bateria_wh_default": 580,
        "motor": "TQ HPR60",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Light e-MTB / Trail",
    },
    {
        "patrones": ["trek fuel exe", "fuel exe"],
        "peso_kg": 18.4,
        "bateria_wh_default": 360,
        "motor": "TQ HPR50",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Light e-MTB",
    },
    {
        "patrones": ["scott lumen"],
        "peso_kg": 16.5,
        "bateria_wh_default": 520,
        "motor": "TQ HPR50",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "XC / Downcountry",
    },
    {
        "patrones": ["mondraker neat"],
        "peso_kg": 18.5,
        "bateria_wh_default": 360,
        "motor": "TQ HPR50",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Light e-MTB",
    },
    {
        "patrones": ["giant trance x advanced e+ elite"],
        "peso_kg": 19.1,
        "bateria_wh_default": 400,
        "motor": "Giant SyncDrive Pro",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Light e-MTB",
    },
    {
        "patrones": ["ktm macina scarp"],
        "peso_kg": 17.8,
        "bateria_wh_default": 500,
        "motor": "Bosch Performance Line SX / CX",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "XC / Downcountry",
    },
    {
        "patrones": ["cube ams hybrid one44"],
        "peso_kg": 17.4,
        "bateria_wh_default": 400,
        "motor": "Bosch Performance Line SX",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Light e-MTB / Downcountry",
    },
    {
        "patrones": ["lapierre e-zesty", "ezesty"],
        "peso_kg": 18.4,
        "bateria_wh_default": 430,
        "motor": "Fazua Ride 60",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Light e-MTB",
    },
    {
        "patrones": ["focus vam2 sl", "focus jam2 sl"],
        "peso_kg": 17.9,
        "bateria_wh_default": 430,
        "motor": "Fazua Ride 60",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Light e-MTB",
    },
    {
        "patrones": ["merida eone-forty", "eone-forty"],
        "peso_kg": 20.6,
        "bateria_wh_default": 630,
        "motor": "Shimano EP8",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail / All Mountain",
    },
    {
        "patrones": ["moustache samedi 29 trail", "samedi 29 trail"],
        "peso_kg": 23.3,
        "bateria_wh_default": 625,
        "motor": "Bosch Performance Line CX",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail",
    },
    {
        "patrones": ["giant reign e+"],
        "peso_kg": 24.2,
        "bateria_wh_default": 625,
        "motor": "Giant SyncDrive Pro (Yamaha)",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Enduro / Trail",
    },
    {
        "patrones": ["giant stance e+"],
        "peso_kg": 23.8,
        "bateria_wh_default": 625,
        "motor": "Giant SyncDrive Sport (Yamaha)",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail",
    },
    {
        "patrones": ["specialized turbo levo", "turbo levo"],
        "peso_kg": 22.1,
        "bateria_wh_default": 700,
        "motor": "Specialized 2.2 (Brose)",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail",
    },
    {
        "patrones": ["orbea wild"],
        "peso_kg": 22.8,
        "bateria_wh_default": 625,
        "motor": "Bosch Performance Line CX",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Enduro / Trail",
    },
    {
        "patrones": ["scott strike eride", "scott patron eride"],
        "peso_kg": 23.5,
        "bateria_wh_default": 625,
        "motor": "Bosch Performance Line CX",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail",
    },
    {
        "patrones": ["trek rail"],
        "peso_kg": 22.9,
        "bateria_wh_default": 625,
        "motor": "Bosch Performance Line CX",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail / Enduro",
    },
    {
        "patrones": ["mondraker crafty"],
        "peso_kg": 23.4,
        "bateria_wh_default": 625,
        "motor": "Bosch Performance Line CX",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail / Enduro",
    },
    {
        "patrones": ["cube stereo hybrid"],
        "peso_kg": 23.4,
        "bateria_wh_default": 625,
        "motor": "Bosch Performance Line CX",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail / All Mountain",
    },
    {
        "patrones": ["cannondale habit neo"],
        "peso_kg": 22.4,
        "bateria_wh_default": 625,
        "motor": "Bosch Performance Line CX",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail",
    },
    {
        "patrones": ["cannondale moterra neo"],
        "peso_kg": 23.8,
        "bateria_wh_default": 625,
        "motor": "Bosch Performance Line CX",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail / Enduro",
    },
    {
        "patrones": ["haibike allmtn", "haibike alltrail"],
        "peso_kg": 24.2,
        "bateria_wh_default": 630,
        "motor": "Yamaha PW-X3 / Bosch CX",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail / All Mountain",
    },
    {
        "patrones": ["ktm macina kapoho", "ktm macina chacana"],
        "peso_kg": 24.5,
        "bateria_wh_default": 750,
        "motor": "Bosch Performance Line CX",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail / All Mountain",
    },
    {
        "patrones": ["bh atomx lynx", "atomx lynx"],
        "peso_kg": 22.8,
        "bateria_wh_default": 720,
        "motor": "Brose S Mag",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail / Enduro",
    },
    {
        "patrones": ["specialized turbo tero x", "turbo tero x"],
        "peso_kg": 21.8,
        "bateria_wh_default": 530,
        "motor": "Specialized Full Power 2.0E",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail",
    },
    {
        "patrones": ["trek powerfly fs"],
        "peso_kg": 23.9,
        "bateria_wh_default": 625,
        "motor": "Bosch Performance Line CX",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail",
    },
]


# ---------------------------------------------------------------------------
# Base de conocimiento sobre documentación/diagnóstico fiable por motor
# ---------------------------------------------------------------------------
def evaluar_documentacion_motor(motor_str: Optional[str], titulo: str = "") -> Tuple[float, str]:
    """
    Evalúa la viabilidad de extraer un informe oficial de diagnóstico del motor y batería.
    Devuelve (puntos sobre 2.0, explicación técnica).
    """
    texto = f"{motor_str or ''} {titulo}".lower()

    if "bosch" in texto:
        return (
            2.0,
            "Alta (Bosch DiagnosticTool 3 genera informe PDF oficial con km reales, "
            "ciclos de carga completos, tiempo por modo de asistencia y registro de errores)",
        )
    if "shimano" in texto or "ep8" in texto or "ep6" in texto or "orbea rise" in texto:
        return (
            1.9,
            "Alta (Shimano E-Tube Project Professional con interfaz PCE02 permite auditar "
            "salud de batería SoH %, ciclos de carga, odómetro interno y fallos registrados)",
        )
    if "specialized" in texto or "brose" in texto or "levo" in texto:
        return (
            1.8,
            "Alta (Specialized Turbo Studio y app Mission Control muestran salud de batería "
            "en %, ciclos exactos, odómetro de motor y números de serie)",
        )
    if any(m in texto for m in ["tq", "fazua", "mahle"]):
        return (
            1.7,
            "Media-Alta (Fazua Toolbox / TQ Service Tool permite verificar ciclos de batería, "
            "estado de celdas y horas de uso del sistema ligero)",
        )
    if "giant" in texto or "syncdrive" in texto or "yamaha" in texto:
        return (
            1.5,
            "Media-Alta (Giant RideControl / diagnóstico Yamaha en taller oficial verifica "
            "salud de EnergyPak, ciclos de carga y odómetro)",
        )
    if "bh" in texto or "2exmag" in texto or "2esmag" in texto or "ilynx" in texto:
        return (
            1.5,
            "Media (diagnóstico en servicio oficial BH Core/2EXMAG verifica estado de celdas "
            "y odómetro; respaldado por 1 año de garantía mecánica de tienda)",
        )
    return (
        1.2,
        "Media (requiere lectura de taller multimarca; cubierta por 1 año de garantía "
        "mecánica de la tienda profesional)",
    )


# ---------------------------------------------------------------------------
# Caché de valoraciones IA
# ---------------------------------------------------------------------------
def _cargar_cache_ia() -> Dict[str, dict]:
    with _CACHE_LOCK:
        if not CACHE_IA_FILE.exists():
            return {}
        try:
            with open(CACHE_IA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}


def _guardar_entrada_cache_ia(cache_key: str, entry: dict) -> None:
    with _CACHE_LOCK:
        CACHE_DIR.mkdir(exist_ok=True)
        actual = {}
        if CACHE_IA_FILE.exists():
            try:
                with open(CACHE_IA_FILE, "r", encoding="utf-8") as f:
                    actual = json.load(f)
            except Exception:
                actual = {}
        actual[cache_key] = entry
        try:
            with open(CACHE_IA_FILE, "w", encoding="utf-8") as f:
                json.dump(actual, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning(f"[IA Caché] No se pudo guardar {CACHE_IA_FILE}: {e}")


# ---------------------------------------------------------------------------
# Paso 1: Enriquecimiento con catálogo técnico local + ficha de tienda
# ---------------------------------------------------------------------------
def completar_con_catalogo(bici: Bicicleta, aplicar_heuristica_peso: bool = True) -> Bicicleta:
    """
    Completa campos faltantes de la bicicleta cruzando su título y datos actuales
    con el catálogo técnico de referencia de modelos e-MTB.
    """
    texto = f"{bici.titulo} {bici.motor or ''} {bici.componentes or ''}".lower()

    for entrada in CATALOGO_EMTB:
        if any(p in texto for p in entrada["patrones"]):
            if bici.peso_kg is None:
                bici.peso_kg = entrada["peso_kg"]
            if bici.bateria_wh is None:
                bici.bateria_wh = entrada["bateria_wh_default"]
            if not bici.motor:
                bici.motor = entrada["motor"]
            if not bici.cuadro_material:
                bici.cuadro_material = entrada["cuadro_material"]
            if bici.suspension_trasera is None:
                bici.suspension_trasera = entrada["suspension_trasera"]
            if not bici.modalidad:
                bici.modalidad = entrada["modalidad"]
            break

    # Corrección de motor en bicicletas BH cuando la tienda confunde transmisión Shimano con el motor:
    # - BH iLynx Race y BH iLynx Trail (sin '+') usan SIEMPRE motor propietario BH 2EXMAG.
    # - BH iLynx+ (con '+') usa bloque Shimano EP801 integrado con batería/sistema propietario BH.
    titulo_lower = bici.titulo.lower()
    if ("bh " in titulo_lower or "ilynx" in titulo_lower) and "ilynx+" not in titulo_lower and "ilynx plus" not in titulo_lower:
        if "ilynx" in titulo_lower and (not bici.motor or "shimano" in bici.motor.lower()):
            bici.motor = "BH 2EXMAG"
        elif "atomx" in titulo_lower and (not bici.motor or "shimano" in bici.motor.lower()):
            bici.motor = "Brose S Mag"
    elif "ilynx+" in titulo_lower or "ilynx plus" in titulo_lower:
        bici.motor = "Shimano EP801 (Sistema/Batería BH)"
        # Si tenía cacheado el peso de la iLynx normal (18.6 kg), corregir al peso real de la iLynx+ (20.4 kg, Fox 38 160mm)
        if bici.peso_kg is not None and bici.peso_kg < 19.5:
            bici.peso_kg = 20.4
        bici.modalidad = "Trail (160mm)"

    # Inferencia adicional por heurística técnica si el modelo no está en la tabla exacta
    if not bici.cuadro_material:
        if any(k in texto for k in ["carbon", "carbono", " m10", " m20", " m-team", "advanced", "cf "]):
            bici.cuadro_material = "Carbono"
        elif any(k in texto for k in ["aluminio", "alloy", "alu", " h10", " h20", " h30"]):
            bici.cuadro_material = "Aluminio"

    if aplicar_heuristica_peso and bici.peso_kg is None:
        # Estimación conservadora basada en material de cuadro y capacidad de batería
        es_carbono = (bici.cuadro_material or "").lower() == "carbono"
        bat = bici.bateria_wh or 540
        if es_carbono and bat <= 560:
            bici.peso_kg = 18.6
        elif not es_carbono and bat <= 540:
            bici.peso_kg = 20.4
        elif es_carbono and bat <= 630:
            bici.peso_kg = 20.8
        else:
            bici.peso_kg = 22.8

    if not bici.modalidad and bici.peso_kg is not None:
        if bici.peso_kg < 21.0:
            bici.modalidad = "Light e-MTB / Trail"
        else:
            bici.modalidad = "Trail"

    return bici


# ---------------------------------------------------------------------------
# Paso 2: Auditoría Pericial Determinista (Perito Mecánico Senior)
# ---------------------------------------------------------------------------
def auditar_perito_mecanico(bici: Bicicleta) -> dict:
    """
    Aplica la Regla Maestra del Perito Mecánico Senior:
    Parte de base 10.0 y aplica restas estrictas e irreversibles + Líneas Rojas:
      - Km > 6.000 -> LÍNEA ROJA (nota máxima 4.5)
      - Peso > 21.0 kg -> LÍNEA ROJA (nota máxima 4.0)
    """
    base = 10.0
    techo = 10.0
    lineas_rojas = []

    km = bici.km
    peso = bici.peso_kg
    precio = bici.precio
    texto_motor = f"{bici.motor or ''} {bici.titulo}".lower()

    # 1. PENALIZACIONES POR KILOMETRAJE
    if km is None:
        delta_km = -2.0
        txt_km = (
            "Km no declarados en ficha (-2.0 pts preventivos). Coste oculto potencial en "
            "transmisión y retenes; exigir lectura de odómetro antes de comprar."
        )
    elif km <= 1000:
        delta_km = 0.0
        txt_km = (
            f"{km} km (-0.0 pts, rango 0-1.000 km): Estado óptimo de reestreno; "
            f"desgaste despreciable en casete, cadena y rodamientos."
        )
    elif km <= 2000:
        delta_km = -1.0
        txt_km = (
            f"{km} km (-1.0 pts, rango 1.001-2.000 km): Rodada y aceptable; "
            f"prever cambio de cadena/pastillas a corto plazo para no marcar coronas."
        )
    elif km <= 4000:
        delta_km = -2.5
        txt_km = (
            f"{km} km (-2.5 pts, rango 2.001-4.000 km): Desgaste medio en transmisión "
            f"y ciclos de celdas; revisar holguras en basculante y mantenimiento de horquilla."
        )
    elif km <= 6000:
        delta_km = -4.5
        txt_km = (
            f"{km} km (-4.5 pts, rango 4.001-6.000 km): Exige cambio de retenes de suspensión, "
            f"revisión de rodamientos de motor y batería con degradación palpable (coste oculto 250-400 €)."
        )
    else:
        delta_km = -5.5
        techo = min(techo, 4.5)
        lineas_rojas.append("LÍNEA ROJA KM >6.000 (máx 4.5)")
        txt_km = (
            f"{km} km (-5.5 pts, >6.000 km -> LÍNEA ROJA ACTIVADA, nota máx 4.5): "
            f"Riesgo crítico de fatiga en celdas, holguras en basculante y desgaste interno del motor."
        )

    # 2. PENALIZACIONES POR PESO
    if peso is None:
        delta_peso = 0.0
        txt_peso = f"Peso estimado en rango ({bici.cuadro_material or 'Carbono'}) (-0.0 pts)."
    elif peso < 19.0:
        delta_peso = 0.5
        txt_peso = (
            f"{peso} kg (+0.5 pts, <19.0 kg): Bonificación por peso pluma en chasis de "
            f"{bici.cuadro_material or 'Carbono'}; mínima inercia y menor estrés en frenos/suspensiones."
        )
    elif peso <= 20.0:
        delta_peso = 0.0
        txt_peso = (
            f"{peso} kg (-0.0 pts, rango 19.1-20.0 kg): Peso neutro y equilibrado para "
            f"Light e-MTB en cuadro de {bici.cuadro_material or 'serie'}."
        )
    elif peso <= 21.0:
        delta_peso = -1.5
        txt_peso = (
            f"{peso} kg (-1.5 pts, rango 20.1-21.0 kg): Al límite del umbral admisible; "
            f"mayor inercia en tramos técnicos y mayor consumo por kilómetro."
        )
    else:
        delta_peso = -6.0
        techo = min(techo, 4.0)
        lineas_rojas.append("LÍNEA ROJA PESO >21.0 kg (máx 4.0)")
        txt_peso = (
            f"{peso} kg (-6.0 pts, >21.0 kg -> LÍNEA ROJA ACTIVADA, nota máx 4.0): "
            f"Incumple especificación ligera; mayor castigo mecánico en frenos, ruedas y basculante."
        )

    # 3. EVALUACIÓN DE MOTOR, CENTRALITA Y DIAGNÓSTICO
    motor_lower = (bici.motor or "").lower()
    titulo_lower = bici.titulo.lower()
    es_marca_bh = (
        any(k in titulo_lower for k in ["bh ", "ilynx", "atomx"])
        or any(k in motor_lower for k in ["2exmag", "2esmag", "bh"])
    )
    es_brose = "brose" in motor_lower
    es_shimano_o_bosch = not es_marca_bh and not es_brose and (
        any(k in motor_lower for k in ["shimano", "ep8", "ep6", "bosch"])
        or any(k in titulo_lower for k in ["ep8", "ep6", "bosch", "orbea rise"])
    )

    if es_marca_bh:
        if (km or 0) > 3000:
            delta_motor = -2.5
            txt_motor = (
                f"Centralita/Motor BH ({bici.motor or 'BH 2EXMAG'}) con {km} km "
                f"(-1.0 pt por centralita BH con software propietario y opaco sin informe PDF veraz "
                f"-1.5 pts extra por superar 3.000 km a ciegas = -2.5 pts): Riesgo alto al no poder "
                f"auditar ciclos reales ni SoH de celdas mediante informe oficial."
            )
        else:
            delta_motor = -1.0
            txt_motor = (
                f"Centralita/Motor BH ({bici.motor or 'BH'}) (-1.0 pt): Penalización directa porque "
                f"BH utiliza una centralita con software propietario y opaco que impide extraer un "
                f"informe pericial veraz en PDF sobre ciclos y salud real de la batería."
            )
    elif es_brose and (km or 0) > 3000:
        delta_motor = -1.5
        txt_motor = (
            f"{bici.motor or 'Brose'} con {km} km (-1.5 pts por >3.000 km): "
            f"Imposibilidad de verificar salud de batería y ciclos sin software cerrado de la marca."
        )
    elif es_shimano_o_bosch:
        delta_motor = 0.0
        _, doc_ref = evaluar_documentacion_motor(bici.motor, bici.titulo)
        txt_motor = f"{bici.motor or 'Shimano/Bosch'} (-0.0 pts): {doc_ref}."
    else:
        delta_motor = 0.0
        _, doc_ref = evaluar_documentacion_motor(bici.motor, bici.titulo)
        txt_motor = (
            f"{bici.motor or 'Motor de serie'} (-0.0 pts, km <=3.000): {doc_ref}."
        )

    # 4. ESTADO DE BATERÍA (Análisis pericial vinculado a Wh y ciclos por km)
    bat = bici.bateria_wh or 540
    ciclos_aprox = max(1, int((km or 1500) / 45))
    if (km or 0) > 6000:
        txt_bateria = (
            f"{bat} Wh (~{ciclos_aprox} ciclos estimados): Degradación severa acumulada; "
            f"alta probabilidad de caída de tensión bajo carga intensa (SoH estimado <80%)."
        )
    elif (km or 0) > 3000:
        txt_bateria = (
            f"{bat} Wh (~{ciclos_aprox} ciclos estimados): Desgaste moderado de celdas "
            f"(SoH estimado 84-89%); verificar equilibrio de celdas en diagnóstico."
        )
    else:
        txt_bateria = (
            f"{bat} Wh (~{ciclos_aprox} ciclos estimados): Salud óptima de celdas "
            f"(SoH estimado 93-99%) respaldada por 1 año de garantía profesional."
        )

    # 5. PRECIO FRENTE A COMPONENTES
    if precio > 3000 and (km or 0) > 2000:
        delta_precio = -1.5
        txt_precio = (
            f"{precio:.0f} € (-1.5 pts por superar 3.000 € con >{km} km): "
            f"Sobrecoste penalizado frente al desgaste acumulado pese al montaje ({bici.componentes or 'serie'})."
        )
    else:
        delta_precio = 0.0
        txt_precio = (
            f"{precio:.0f} € (-0.0 pts, rango 2.000-3.000 €): "
            f"Precio coherente para chasis {bici.cuadro_material or 'Carbono'} y montaje ({bici.componentes or 'serie'})."
        )

    nota_aritmetica = base + delta_km + delta_peso + delta_motor + delta_precio
    nota_final = round(max(0.0, min(10.0, nota_aritmetica, techo)), 2)

    signo_peso = f"+{delta_peso:.1f}" if delta_peso > 0 else f"{delta_peso:.1f}"
    formula_str = (
        f"Base 10.0 {delta_km:.1f} (Km) {signo_peso} (Peso) "
        f"{delta_motor:.1f} (Motor) {delta_precio:.1f} (Precio) = {nota_aritmetica:.1f}"
    )
    if lineas_rojas:
        formula_str += f" -> Límite [{', '.join(lineas_rojas)}] => {nota_final}/10"
    else:
        formula_str += f" => {nota_final}/10"

    return {
        "nota_final": nota_final,
        "nota_aritmetica": round(nota_aritmetica, 2),
        "techo": techo,
        "lineas_rojas": lineas_rojas,
        "delta_km": delta_km,
        "delta_peso": delta_peso,
        "delta_motor": delta_motor,
        "delta_precio": delta_precio,
        "formula_str": formula_str,
        "txt_km": txt_km,
        "txt_peso": txt_peso,
        "txt_motor": txt_motor,
        "txt_bateria": txt_bateria,
        "txt_precio": txt_precio,
    }


def valorar_autonomo(bici: Bicicleta) -> Tuple[float, str]:
    """
    Calcula la nota de oportunidad (0.0 a 10.0) y genera la auditoría técnica
    del Perito Mecánico Senior en los 5 ejes con justificación matemática exacta.
    """
    audit = auditar_perito_mecanico(bici)
    desglose = (
        f"🧮 Cálculo Pericial: {audit['formula_str']}\n"
        f"• 🛣️ Km: {audit['txt_km']}\n"
        f"• ⚖️ Peso: {audit['txt_peso']}\n"
        f"• 🔍 Diagnóstico motor: {audit['txt_motor']}\n"
        f"• 🔋 Estado batería: {audit['txt_bateria']}\n"
        f"• ⚙️ Componentes/Precio: {audit['txt_precio']}"
    )
    return audit["nota_final"], desglose


# ---------------------------------------------------------------------------
# Paso 3: Enriquecimiento y valoración con Gemini Flash (gemini-3.5-flash)
# ---------------------------------------------------------------------------
def _llamar_gemini_api(prompt: str, usar_busqueda: bool = False) -> Optional[dict]:
    """
    Invoca Gemini Flash (gemini-3.5-flash -> fallback gemini-3.5-flash-lite).
    Devuelve el dict JSON parseado o None si no hay clave o falla la cuota.
    """
    api_key = cfg.GEMINI_API_KEY
    if not api_key:
        return None

    for model in cfg.GEMINI_MODELS:
        url = f"{cfg.GEMINI_API_URL.format(model=model)}?key={api_key}"
        payload: dict = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
            },
        }
        if usar_busqueda:
            payload["tools"] = [{"google_search": {}}]
            payload["generationConfig"].pop("responseMimeType", None)

        try:
            resp = requests.post(url, json=payload, timeout=25)
            if resp.status_code != 200:
                log.debug(f"[Gemini {model}] HTTP {resp.status_code}: {resp.text[:180]}")
                continue

            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                continue

            parts = candidates[0].get("content", {}).get("parts", [])
            texto_respuesta = "".join(p.get("text", "") for p in parts if "text" in p).strip()
            if not texto_respuesta:
                continue

            match = re.search(r"\{.*\}", texto_respuesta, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except Exception as e:
            log.debug(f"[Gemini {model}] Excepción: {e}")
            continue

    return None


def enriquecer_y_valorar_bici(bici: Bicicleta) -> Tuple[Bicicleta, float, str]:
    """
    Flujo híbrido completo bajo las reglas del Perito Mecánico Senior:
      1. Extrae ficha de producto del sitio con Scrapling (enriquecer_bici).
      2. Completa especificaciones de referencia con el catálogo técnico local.
      3. Si GEMINI_API_KEY está activa, consulta Gemini Flash con la tabla estricta
         de restas y Líneas Rojas del Perito Mecánico Senior, y audita la nota final
         matemáticamente para impedir medias optimistas.
      4. Si Gemini no está disponible o falla, usa el motor pericial autónomo local.
    """
    # 1. Enriquecimiento desde la ficha HTML del sitio (con caché local)
    try:
        bici = enriquecer_bici(bici, url_ficha=bici.url)
    except Exception as e:
        log.warning(f"[IA] Error en enriquecer_bici para {bici.titulo}: {e}")

    # 2. Enriquecimiento desde catálogo técnico de modelos e-MTB
    bici = completar_con_catalogo(bici, aplicar_heuristica_peso=False)

    # Verificar caché de valoración IA (versión v3 perito con penalización BH -1.0) para esta bici y precio
    cache_key = f"perito_v3:{bici.sitio}:{bici.bici_id}:{int(bici.precio)}"
    cache_ia = _cargar_cache_ia()
    if cache_key in cache_ia:
        entry = cache_ia[cache_key]
        for campo in ("talla", "modalidad", "peso_kg", "bateria_wh", "cuadro_material",
                      "motor", "km", "ano", "componentes", "suspension_trasera"):
            if entry.get(campo) is not None and getattr(bici, campo, None) is None:
                setattr(bici, campo, entry[campo])
        bici = completar_con_catalogo(bici, aplicar_heuristica_peso=True)
        audit_cached = auditar_perito_mecanico(bici)
        return bici, audit_cached["nota_final"], str(entry["desglose"])

    # Pre-auditoría con los datos conocidos hasta ahora
    audit_pre = auditar_perito_mecanico(bici)

    # 3. Clasificación y auditoría con Gemini Flash como Perito Mecánico Senior
    prompt = f"""Actúa como un Perito Mecánico Senior de bicicletas eléctricas. Tu tarea es auditar los datos de una e-MTB de ocasión y generar una "Nota de Oportunidad" (0.0 a 10.0).

REGLA MAESTRA: NUNCA hagas una media optimista. La evaluación parte de una nota base de 10.0 y se aplican restas estrictas e irreversibles según la siguiente tabla de penalizaciones:

1. PENALIZACIONES POR KILOMETRAJE (Factor Crítico):
- De 0 a 1.000 km: -0.0 puntos (Estado óptimo).
- De 1.001 a 2.000 km: -1.0 puntos (Rodada, aceptable).
- De 2.001 a 4.000 km: -2.5 puntos (Desgaste medio en transmisión y celdas).
- De 4.001 a 6.000 km: -4.5 puntos (Exige cambio de retenes, revisión de motor y batería mermada).
- Más de 6.000 km: LÍNEA ROJA. La nota máxima final NUNCA puede superar el 4.5, independientemente de los componentes o el cuadro.

2. PENALIZACIONES POR PESO:
- Menos de 19.0 kg: +0.5 puntos (Bonificación por peso pluma).
- De 19.1 a 20.0 kg: -0.0 puntos.
- De 20.1 a 21.0 kg: -1.5 puntos.
- Más de 21.0 kg: LÍNEA ROJA. Nota máxima de 4.0.

3. EVALUACIÓN DE MOTOR, CENTRALITA Y DIAGNÓSTICO:
- Motor Shimano (EP8/EP8-RS) o Bosch (CX) en marcas con diagnóstico abierto: -0.0 puntos (Permiten informe PDF pericial oficial, máxima transparencia).
- Bicicletas BH (iLynx, AtomX, BH 2EXMAG): Resta SIEMPRE -1.0 punto base porque no se le puede sacar un informe veraz en PDF de su centralita al tener un software propietario y opaco.
- Además, en BH 2EXMAG o Brose con más de 3.000 km: resta -1.5 puntos extra por la imposibilidad de verificar salud de batería y ciclos sin software cerrado de la marca (total -2.5 pts en BH >3.000 km).

4. PRECIO FRENTE A COMPONENTES:
- Rango base: 2.000 € a 3.000 €.
- Si supera los 3.000 € (ej. 3.100 €) y supera los 2.000 km: -1.5 puntos.

Datos extraídos de la bicicleta ({bici.sitio}):
- Modelo/Título: {bici.titulo}
- Precio: {bici.precio} €
- Talla: {bici.talla or 'M'}
- Peso conocido (kg): {bici.peso_kg if bici.peso_kg is not None else 'inferir peso real de catálogo para este modelo exacto'}
- Batería (Wh): {bici.bateria_wh if bici.bateria_wh is not None else 'desconocida'}
- Motor: {bici.motor or 'inferir motor real del modelo'}
- Cuadro: {bici.cuadro_material or 'inferir material'}
- Kilómetros: {bici.km if bici.km is not None else 'no declarados'}
- Año: {bici.ano if bici.ano is not None else 'desconocido'}
- Componentes: {bici.componentes or 'de serie'}
- Cálculo aritmético preliminar: {audit_pre['formula_str']}

PROCEDIMIENTO DE SALIDA (CHAIN OF THOUGHT):
Antes de dar la respuesta final, realiza el cálculo aritmético paso a paso en base a estas reglas. Si una línea roja se activa (ej. >6.000 km o >21.0 kg), limita la nota máxima automáticamente.
Redacta la valoración en 5 ejes (Km, Peso, Diagnóstico, Batería, Precio), justificando matemáticamente por qué se han restado los puntos. Sé crítico, directo y técnico, advirtiendo de los costes ocultos (rodamientos, retenes, celdas degradadas) en kilometrajes altos.

Devuelve ÚNICAMENTE un objeto JSON válido con esta estructura exacta:
{{
  "peso_kg": numero_float_peso_real_catalogo,
  "bateria_wh": numero_int_wh,
  "motor": "marca y modelo real del motor",
  "cuadro_material": "Carbono o Aluminio",
  "suspension_trasera": "si o no",
  "modalidad": "Light e-MTB / XC / Downcountry / Trail",
  "ano": numero_int_ano,
  "componentes": "resumen breve de transmisión y suspensiones",
  "calculo_paso_a_paso": "Base 10.0 - X.X (Km) ... = Nota",
  "nota": numero_float_de_0_a_10,
  "km_analisis": "justificación matemática de la resta por km y costes ocultos (retenes, transmisión, rodamientos)",
  "peso_analisis": "justificación matemática por peso (+/- puntos o línea roja) y comportamiento dinámico",
  "motor_doc_analisis": "justificación matemática del motor (-0.0 o -1.5 pts) y viabilidad de informe pericial PDF",
  "bateria_analisis": "auditoría crítica de degradación de celdas, ciclos estimados y riesgo fuera de garantía",
  "componentes_analisis": "justificación matemática del precio (-0.0 o -1.5 pts) frente a los componentes equipados"
}}"""

    res_gemini = _llamar_gemini_api(prompt, usar_busqueda=False)
    if res_gemini:
        try:
            if bici.peso_kg is None and res_gemini.get("peso_kg"):
                bici.peso_kg = float(res_gemini["peso_kg"])
            if bici.bateria_wh is None and res_gemini.get("bateria_wh"):
                bici.bateria_wh = int(res_gemini["bateria_wh"])
            if not bici.motor and res_gemini.get("motor"):
                bici.motor = str(res_gemini["motor"])
            if not bici.cuadro_material and res_gemini.get("cuadro_material"):
                bici.cuadro_material = str(res_gemini["cuadro_material"])
            if bici.suspension_trasera is None and res_gemini.get("suspension_trasera"):
                bici.suspension_trasera = str(res_gemini["suspension_trasera"]).lower()
            if not bici.modalidad and res_gemini.get("modalidad"):
                bici.modalidad = str(res_gemini["modalidad"])
            if bici.ano is None and res_gemini.get("ano"):
                bici.ano = int(res_gemini["ano"])
            if not bici.componentes and res_gemini.get("componentes"):
                bici.componentes = str(res_gemini["componentes"])

            bici = completar_con_catalogo(bici, aplicar_heuristica_peso=True)

            # Re-auditar matemáticamente con los campos definitivos (garantiza que la regla maestra se cumpla al 100%)
            audit_post = auditar_perito_mecanico(bici)
            nota_final = audit_post["nota_final"]

            desglose_ia = (
                f"🧮 Auditoría Pericial: {audit_post['formula_str']}\n"
                f"• 🛣️ Km: {res_gemini.get('km_analisis', audit_post['txt_km'])}\n"
                f"• ⚖️ Peso: {res_gemini.get('peso_analisis', audit_post['txt_peso'])}\n"
                f"• 🔍 Diagnóstico motor: {res_gemini.get('motor_doc_analisis', audit_post['txt_motor'])}\n"
                f"• 🔋 Estado batería: {res_gemini.get('bateria_analisis', audit_post['txt_bateria'])}\n"
                f"• 💰 Precio/Componentes: {res_gemini.get('componentes_analisis', audit_post['txt_precio'])}"
            )

            entry_data = {
                "talla": bici.talla,
                "modalidad": bici.modalidad,
                "peso_kg": bici.peso_kg,
                "bateria_wh": bici.bateria_wh,
                "cuadro_material": bici.cuadro_material,
                "motor": bici.motor,
                "km": bici.km,
                "ano": bici.ano,
                "componentes": bici.componentes,
                "suspension_trasera": bici.suspension_trasera,
                "nota": nota_final,
                "desglose": desglose_ia,
            }
            _guardar_entrada_cache_ia(cache_key, entry_data)
            log.info(
                f"[Perito IA] {bici.titulo} -> {nota_final}/10 "
                f"(km={bici.km}, peso={bici.peso_kg} kg) | {audit_post['formula_str']}"
            )
            return bici, nota_final, desglose_ia
        except Exception as e:
            log.warning(f"[Gemini Flash] Error procesando respuesta JSON para {bici.titulo}: {e}")

    # 4. Fallback al motor autónomo pericial local (100% sin API)
    bici = completar_con_catalogo(bici, aplicar_heuristica_peso=True)
    nota_auto, desglose_auto = valorar_autonomo(bici)
    log.info(f"[Perito Autónomo] {bici.titulo} -> {nota_auto}/10 (km={bici.km}, peso={bici.peso_kg} kg)")
    return bici, nota_auto, desglose_auto
