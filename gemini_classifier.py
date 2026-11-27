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
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests

import config as cfg
from evaluator import es_bici_bh
from models import Bicicleta
from scrapers.enriquecedor_web import (
    completar_desde_duckduckgo,
    enriquecer_bici,
    _buscar_en_cache,
    _extraer_range_extender,
)

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
        "recorrido_mm": 120,
        "componentes_default": "Fox 34 Float / Shimano XT 12v",
    },
    {
        "patrones": ["bh ilynx+ dl", "ilynx+ dl"],
        "peso_kg": 21.6,
        "bateria_wh_default": 600,
        "motor": "DJI Avinox",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail / Enduro",
        "recorrido_mm": 160,
    },
    {
        "patrones": ["bh ilynx+ nx", "ilynx+ nx"],
        "peso_kg": 22.5,
        "bateria_wh_default": 600,
        "motor": "Bosch Performance Line CX",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 150,
    },
    {
        "patrones": ["olympia hekton"],
        "peso_kg": 22.2,
        "bateria_wh_default": 800,
        "motor": "DJI Avinox",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Enduro",
        "recorrido_mm": 160,
    },
    {
        "patrones": ["megamo reason al"],
        "peso_kg": 22.0,
        "bateria_wh_default": 850,
        "motor": "DJI Avinox",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Enduro",
        "recorrido_mm": 160,
    },
    {
        "patrones": ["megamo reason air"],
        "peso_kg": 22.04,
        "bateria_wh_default": 800,
        "motor": "DJI Avinox M2S",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 140,
    },
    {
        "patrones": ["megamo ryal"],
        "peso_kg": 23.5,
        "bateria_wh_default": 800,
        "motor": "DJI Avinox M2",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Enduro",
        "recorrido_mm": 160,
    },
    {
        "patrones": ["bh ilynx+ sl enduro", "ilynx+ sl enduro"],
        "peso_kg": 22.6,
        "bateria_wh_default": 630,
        "motor": "Shimano EP6",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Enduro",
        "recorrido_mm": 160,
    },
    {
        "patrones": ["bh ilynx+ enduro", "ilynx+ enduro"],
        "peso_kg": 22.4,
        "bateria_wh_default": 630,
        "motor": "Shimano EP801",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Enduro",
        "recorrido_mm": 170,
    },
    {
        "patrones": ["bh ilynx+ sl trail", "ilynx+ sl trail", "bh ilynx+ sl", "ilynx+ sl"],
        "peso_kg": 22.8,
        "bateria_wh_default": 630,
        "motor": "Shimano EP6",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 140,
    },
    {
        "patrones": ["bh ilynx+ trail carbon 8.7", "ilynx+ trail carbon 8.7"],
        "peso_kg": 21.2,
        "bateria_wh_default": 630,
        "motor": "Shimano EP801",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 150,
        "componentes_default": "Fox 36 Float Performance / Fox Float X / Shimano XT 12v",
    },
    {
        "patrones": ["bh ilynx+ trail carbon", "ilynx+ trail carbon", "ilynx+"],
        "peso_kg": 20.4,
        "bateria_wh_default": 540,
        "motor": "Shimano EP801",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 160,
        "componentes_default": "Fox 36 Float / Shimano XT 12v",
    },
    {
        "patrones": ["bh ilynx trail carbon", "ilynx trail carbon"],
        "peso_kg": 18.6,
        "bateria_wh_default": 540,
        "motor": "BH 2EXMAG",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 150,
        "componentes_default": "Fox 36 Float / Shimano XT 12v",
    },
    {
        "patrones": ["bh ilynx race", "ilynx race"],
        "peso_kg": 18.9,
        "bateria_wh_default": 540,
        "motor": "BH 2EXMAG",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "XC / Downcountry",
        "recorrido_mm": 120,
        "componentes_default": "Fox 34 Float / Shimano Deore-XT 12v",
    },
    {
        "patrones": ["bh ilynx trail", "ilynx trail"],
        "peso_kg": 19.6,
        "bateria_wh_default": 540,
        "motor": "BH 2EXMAG",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 150,
        "componentes_default": "RockShox Recon-Fox 34 / Shimano Deore 12v",
    },
    {
        "patrones": ["bh ilynx 9.", "bh ilynx+ 9."],
        "peso_kg": 22.2,
        "bateria_wh_default": 630,
        "motor": "Bosch Performance Line CX / Shimano EP801",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Enduro",
        "recorrido_mm": 160,
    },
    {
        "patrones": ["orbea rise lt h", "orbea rise lt h10", "orbea rise lt h20", "orbea rise lt h30"],
        "peso_kg": 21.8,
        "bateria_wh_default": 630,
        "motor": "Shimano EP600-RS",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 150,
    },
    {
        "patrones": ["orbea rise lt"],
        "peso_kg": 19.5,
        "bateria_wh_default": 630,
        "motor": "Shimano EP801-RS Gen2",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 150,
        "componentes_default": "Fox 36 Float / Fox Float X / Shimano SLX-XT 12v",
    },
    {
        "patrones": ["orbea rise sl h", "orbea rise sl h10", "orbea rise sl h20", "orbea rise sl h30"],
        "peso_kg": 20.2,
        "bateria_wh_default": 540,
        "motor": "Shimano EP801-RS Gen2",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 140,
        "componentes_default": "Fox 34 Float / Shimano Deore-SLX 12v",
    },
    {
        "patrones": [
            "orbea rise m10", "orbea rise m15", "orbea rise m20", "orbea rise m-team", "orbea rise m-ltd",
            "orbea rise sl m10", "orbea rise sl m20", "orbea rise m-pro", "orbea rise carbon", "orbea rise sl",
        ],
        "peso_kg": 18.3,
        "bateria_wh_default": 540,
        "motor": "Shimano EP801 RS",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 140,
        "componentes_default": "Fox 34 Float Performance / Shimano SLX-XT 12v",
    },
    {
        "patrones": ["orbea rise h", "orbea riseh", "orbea rise h10", "orbea rise h15", "orbea rise h20", "orbea rise h30"],
        "peso_kg": 20.5,
        "bateria_wh_default": 540,
        "motor": "Shimano EP8-RS",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 140,
        "componentes_default": "Marzocchi Bomber Z2 - Fox 34 Float / Fox Float / Shimano Deore-SLX 12v",
    },
    {
        "patrones": ["amflow tl", "am flow tl"],
        "peso_kg": 22.6,
        "bateria_wh_default": 800,
        "motor": "DJI Avinox M2",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "All Mountain / SUV",
        "recorrido_mm": 140,
    },
    {
        "patrones": ["amflow pl carbon", "amflow pl", "am flow pl"],
        "peso_kg": 19.8,
        "bateria_wh_default": 600,
        "motor": "DJI Avinox",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail / All Mountain",
        "recorrido_mm": 150,
        "componentes_default": "Fox 36 Performance / Fox Float X / SRAM GX Eagle 12v",
    },
    {
        "patrones": ["cannondale moterra sl", "cannondale moterra neo sl", "moterra neo sl", "moterra sl"],
        "peso_kg": 19.8,
        "bateria_wh_default": 601,
        "motor": "Shimano EP801",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 150,
        "componentes_default": "Fox 36 Performance / Fox Float X / Shimano XT-Deore 12v",
    },
    {
        "patrones": ["mmr kaizen"],
        "peso_kg": 18.6,
        "bateria_wh_default": 400,
        "motor": "Bosch Performance Line SX",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 140,
        "componentes_default": "RockShox Pike / Fox Float / SRAM GX Eagle 12v",
    },
    {
        "patrones": ["ghost path riot", "path riot"],
        "peso_kg": 19.2,
        "bateria_wh_default": 430,
        "motor": "Fazua Ride 60",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail / Enduro",
        "recorrido_mm": 150,
    },
    {
        "patrones": ["mondraker dune"],
        "peso_kg": 19.6,
        "bateria_wh_default": 400,
        "motor": "Bosch Performance Line SX",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Enduro",
        "recorrido_mm": 170,
    },
    {
        "patrones": ["pivot shuttle sl", "shuttle sl"],
        "peso_kg": 18.5,
        "bateria_wh_default": 430,
        "motor": "Fazua Ride 60",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 140,
    },
    {
        "patrones": ["specialized turbo levo sl comp alloy", "levo sl comp alloy", "turbo levo sl alloy", "levo sl alloy"],
        "peso_kg": 20.1,
        "bateria_wh_default": 480,
        "motor": "Specialized SL 1.2",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 150,
        "componentes_default": "Fox 36 Rhythm / Fox Float / SRAM NX Eagle 12v",
    },
    {
        "patrones": ["specialized turbo levo sl", "levo sl"],
        "peso_kg": 17.9,
        "bateria_wh_default": 480,
        "motor": "Specialized SL 1.1 / 1.2",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 150,
        "componentes_default": "Fox 34-36 Performance / SRAM GX-XO1 Eagle 12v",
    },
    {
        "patrones": ["trek fuel+ ex 9", "fuel+ ex 9"],
        "peso_kg": 19.3,
        "bateria_wh_default": 580,
        "motor": "TQ HPR60",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 150,
    },
    {
        "patrones": ["trek fuel+ ex", "fuel+ ex"],
        "peso_kg": 21.08,
        "bateria_wh_default": 580,
        "motor": "TQ HPR60",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 150,
    },
    {
        "patrones": ["trek fuel exe", "fuel exe"],
        "peso_kg": 18.4,
        "bateria_wh_default": 360,
        "motor": "TQ HPR50",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 140,
    },
    {
        "patrones": ["bmc fourstroke amp lt", "fourstroke amp lt", "fourstroke amplt", "bmc fourstroke"],
        "peso_kg": 18.5,
        "bateria_wh_default": 360,
        "motor": "TQ HPR50",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "XC / Downcountry",
        "recorrido_mm": 120,
    },
    {
        "patrones": ["scott lumen"],
        "peso_kg": 16.5,
        "bateria_wh_default": 360,
        "motor": "TQ HPR50",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "XC / Downcountry",
        "recorrido_mm": 130,
    },
    {
        "patrones": ["mondraker neat"],
        "peso_kg": 18.5,
        "bateria_wh_default": 360,
        "motor": "TQ HPR50",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 150,
    },
    {
        "patrones": ["giant trance x advanced e+ elite"],
        "peso_kg": 19.1,
        "bateria_wh_default": 400,
        "motor": "Giant SyncDrive Pro",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 140,
    },
    {
        "patrones": ["ktm macina scarp sx", "macina scarp"],
        "peso_kg": 18.5,
        "bateria_wh_default": 400,
        "motor": "Bosch Performance Line SX",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 140,
    },
    {
        "patrones": ["wilier urta hybrid", "urta hybrid"],
        "peso_kg": 16.4,
        "bateria_wh_default": 430,
        "motor": "Fazua Ride 60",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "XC / Downcountry",
        "recorrido_mm": 120,
    },
    {
        "patrones": ["cube ams hybrid one44"],
        "peso_kg": 17.4,
        "bateria_wh_default": 400,
        "motor": "Bosch Performance Line SX",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 140,
    },
    {
        "patrones": ["lapierre e-zesty", "ezesty"],
        "peso_kg": 18.4,
        "bateria_wh_default": 430,
        "motor": "Fazua Ride 60",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 140,
    },
    {
        "patrones": ["focus vam2 sl", "focus vam 2 sl", "focus vam 8.7 sl", "focus vam 8.8 sl", "focus vam2", "focus vam 2"],
        "peso_kg": 17.5,
        "bateria_wh_default": 430,
        "motor": "Fazua Ride 60",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "XC / Downcountry",
        "recorrido_mm": 130,
    },
    {
        "patrones": ["haibike lyke"],
        "peso_kg": 18.8,
        "bateria_wh_default": 430,
        "motor": "Fazua Ride 60",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 140,
    },
    {
        "patrones": ["santa cruz heckler sl", "heckler sl"],
        "peso_kg": 19.3,
        "bateria_wh_default": 430,
        "motor": "Fazua Ride 60",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 150,
    },
    {
        "patrones": ["focus jam2 sl", "focus jam 2 sl", "focus jam2 8.", "focus jam 2 8."],
        "peso_kg": 18.5,
        "bateria_wh_default": 430,
        "motor": "Fazua Ride 60",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 150,
    },
    {
        "patrones": ["focus jam2", "focus jam 2"],
        "peso_kg": 23.8,
        "bateria_wh_default": 625,
        "motor": "Bosch Performance Line CX",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 150,
    },
    {
        "patrones": ["merida eone-forty", "eone-forty"],
        "peso_kg": 23.0,
        "bateria_wh_default": 630,
        "motor": "Shimano EP8",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail / All Mountain",
    },
    {
        "patrones": ["merida eone-eighty", "eone-eighty", "eone eighty"],
        "peso_kg": 27.0,
        "bateria_wh_default": 800,
        "motor": "Bosch Performance Line CX",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Enduro",
        "recorrido_mm": 180,
    },
    {
        "patrones": ["merida etmo"],
        "peso_kg": 26.8,
        "bateria_wh_default": 800,
        "motor": "Bosch Performance Line CX",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 150,
    },
    {
        "patrones": ["focus sam"],
        "peso_kg": 25.0,
        "bateria_wh_default": 625,
        "motor": "Bosch Performance Line CX",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Enduro",
        "recorrido_mm": 170,
    },
    {
        "patrones": ["raymon railray", "raymon trailray"],
        "peso_kg": 26.0,
        "bateria_wh_default": 800,
        "motor": "Yamaha",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Enduro",
        "recorrido_mm": 180,
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
        "peso_kg": 22.8,
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
        "peso_kg": 23.2,
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
        "patrones": ["bh atomx lynx", "atomx lynx", "bh atome", "atome lynx"],
        "peso_kg": 22.8,
        "bateria_wh_default": 720,
        "motor": "Brose S Mag / Shimano EP6",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail / Enduro",
    },
    {
        "patrones": ["megamo flame", "megamo reach"],
        "peso_kg": 23.8,
        "bateria_wh_default": 800,
        "motor": "Bosch Performance Line CX",
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
    {
        "patrones": ["specialized turbo kenevo sl", "kenevo sl"],
        "peso_kg": 19.4,
        "bateria_wh_default": 320,
        "motor": "Specialized SL 1.1 / 1.2",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail / Enduro",
    },
    {
        "patrones": ["ghost e-asx"],
        "peso_kg": 24.2,
        "bateria_wh_default": 750,
        "motor": "Bosch Performance Line CX",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail / Enduro",
    },
    {
        "patrones": ["ghost e-riot", "ghost riot am"],
        "peso_kg": 23.5,
        "bateria_wh_default": 750,
        "motor": "Bosch Performance Line CX",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Enduro / Trail",
    },
    {
        "patrones": ["bh xtep"],
        "peso_kg": 22.8,
        "bateria_wh_default": 720,
        "motor": "Shimano EP8",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail",
    },
    {
        "patrones": ["berria mako hybrid", "mako hybrid", "berria mako"],
        "peso_kg": 22.8,
        "bateria_wh_default": 720,
        "motor": "Polini E-P3+ / Bafang M500",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail / All Mountain",
        "recorrido_mm": 150,
    },
    {
        "patrones": ["mondraker scree"],
        "peso_kg": 24.9,
        "bateria_wh_default": 600,
        "motor": "Bosch Performance Line CX",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail",
        "recorrido_mm": 150,
    },
    {
        "patrones": ["raymon trailray", "raymon ridok", "raymon korak", "raymon ravor", "raymon tarok"],
        "peso_kg": 23.5,
        "bateria_wh_default": 630,
        "motor": "Yamaha PW-X3 / Bosch CX / Panasonic",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail / Enduro",
    },
    {
        "patrones": ["mondraker dusk"],
        "peso_kg": 23.5,
        "bateria_wh_default": 630,
        "motor": "Shimano EP8",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail / Enduro",
    },
    {
        "patrones": ["husqvarna mc", "mountain cross"],
        "peso_kg": 23.5,
        "bateria_wh_default": 630,
        "motor": "Shimano EP8",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail / All Mountain",
    },
]


# ---------------------------------------------------------------------------
# Base de conocimiento sobre documentación/diagnóstico fiable por motor
# ---------------------------------------------------------------------------
def evaluar_documentacion_motor(
    motor_str: Optional[str],
    titulo: str = "",
    garantia_anos: Optional[int] = None,
) -> Tuple[float, str]:
    """
    Evalúa la viabilidad de extraer un informe oficial de diagnóstico del motor y batería.
    Devuelve (puntos sobre 2.0, explicación técnica).
    """
    texto = f"{motor_str or ''} {titulo}".lower()
    sin_garantia_tienda = garantia_anos == 0
    sufijo_bh = (
        "venta entre particulares sin garantía de tienda (exigir factura e informe oficial previo)"
        if sin_garantia_tienda
        else "respaldado por garantía mecánica profesional de tienda"
    )
    sufijo_otro = (
        "venta entre particulares sin garantía mecánica de tienda"
        if sin_garantia_tienda
        else "cubierta por garantía mecánica de tienda profesional"
    )

    es_ilynx_plus = "ilynx+" in texto or "ilynx plus" in texto
    es_motor_cerrado_bh = (
        not es_ilynx_plus
        and (
            "2exmag" in texto
            or "2esmag" in texto
            or "atomx" in texto
            or "ilynx" in texto
            or (
                es_bici_bh(Bicicleta(sitio="", bici_id="", titulo=titulo, precio=0.0, url="", motor=motor_str))
                and "shimano" not in texto
                and "ep8" not in texto
                and "ep6" not in texto
            )
        )
    )

    if es_motor_cerrado_bh:
        return (
            1.0,
            f"Baja-Media (motor propietario cerrado BH 2EXMAG / Brose antiguo: BH no genera informe PDF "
            f"oficial verificable de odómetro real, ciclos ni SoH de batería; {sufijo_bh})",
        )
    if "shimano" in texto or "ep8" in texto or "ep6" in texto or "orbea rise" in texto or es_ilynx_plus:
        return (
            1.9,
            "Alta (Shimano E-Tube Project / PCE02 abierto y auditable: permite verificar salud de batería SoH %, "
            "ciclos de carga, odómetro interno y registro de errores)",
        )
    if "specialized" in texto or "levo" in texto or "kenevo" in texto:
        return (
            1.9,
            "Alta (Specialized Turbo Studio / app propia permiten auditar salud de batería SoH %, "
            "ciclos exactos, odómetro real y números de serie)",
        )
    if "bosch" in texto:
        return (
            1.6,
            "Media-Alta (Bosch NO muestra ciclos ni salud química SoH en la app de usuario; "
            "requiere lectura presencial con interfaz de taller oficial Bosch DiagnosticTool 3)",
        )
    if any(m in texto for m in ["tq", "fazua", "mahle"]):
        return (
            1.6,
            "Media-Alta (Fazua Toolbox / TQ Service Tool en taller verifica ciclos de batería y horas de uso)",
        )
    if "giant" in texto or "syncdrive" in texto or "yamaha" in texto:
        return (
            1.4,
            "Media (sistema propietario; Giant RideControl / taller Yamaha necesario para verificar SoH y ciclos)",
        )
    return (
        1.1,
        f"Baja-Media (motor no identificado o cerrado, requiere diagnosis de taller; {sufijo_otro})",
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
_MARCAS_EMTB_RE = re.compile(
    r"\b(?:"
    r"orbea|bh|specialized|trek|scott|mondraker|giant|cannondale|focus|cube|"
    r"haibike|lapierre|ktm|merida|ghost|moustache|bulls|berria|mmr|megamo|"
    r"bianchi|husqvarna|rocky\s+mountain|conway|flyer|gasgas|canyon|commencal|"
    r"santa\s+cruz|pivot|amflow|niner|fantic|raymon|norco|yeti|whyte|marin|"
    r"wilier|olympia|rotwild|corratec|conor|carver|ecobike|whistle|atala|"
    r"winora|simplon|stilus|rockrider|nicolai|scor"
    r")\b"
)

_MODELOS_IDENTIFICABLES_RE = re.compile(
    r"\b(?:"
    r"rise|wild|occam|rallon|urrun|diem|kemen|vibe|gain|"
    r"i?lynx|atom\s*x|xtep|core|"
    r"levo|kenevo|tero|fuel\s*\+?[\s\-]*ex\w*|rail|powerfly|e-?caliber|"
    r"lumen|strike|patron|genius|ransom|aspect|"
    r"crafty|dusk|neat|dune|level|chaser|prime|"
    r"trance|reign|stance|talon|fathom|"
    r"moterra|habit|scalpel|"
    r"jam\s*2?|thron|vam\s*2?|sam\s*2?|jarifa|aventura|"
    r"stereo(?:\s+hybrid)?|ams(?:\s+hybrid)?|reaction|nuride|"
    r"allmtn|alltrail|xduro|sduro|fullseven|fullnine|lyke|"
    r"overvolt|e-?zesty|ezesty|kapoho|scarp|chacana|lycan|macina|"
    r"eone[\-\s]?forty|eone[\-\s]?sixty|e-?asx|e-?riot|riot|kato|"
    r"samedi|game|sonic|copperhead|e-?stream|"
    r"mako|polestar|x-?bolt|kaizen|kenta|kore|crave|ayron|ridon|"
    r"t-?tronik|e-?omnium|e-?vertic|"
    r"mountain\s+cross|light\s+cross|hard\s+cross|mc\s*\d|lc\s*\d|hc\s*\d|"
    r"instinct|altitude|powerplay|xyron|cairon|goroc|uproc|"
    r"spectral|neuron|torque|grand\s+canyon|strive|meta\s+power|clash|"
    r"heckler|bullit|valamar|shuttle|firebird|mach|pl\s+carbon|rip|rdo|"
    r"xf1|integra|lt2|e-?feel|e\.?\s*\d{3}|no\s+pogo|hybrid\s+\d+"
    r")\b"
)

_STOPWORDS_MODELO_GENERICO = {
    "bicicleta", "bici", "electrica", "ebike", "e", "bike", "mtb", "emtb",
    "montana", "doble", "suspension", "carbono", "carbon", "aluminio", "alu",
    "alloy", "nueva", "nuevo", "estrenar", "reacondicionada", "seminueva",
    "oferta", "chollo", "urgente", "negociable", "talla", "size", "esta", "como",
    "km", "motor", "bosch", "shimano", "yamaha", "brose", "bateria", "wh",
    "garantia", "ano", "anos", "de", "la", "el", "los", "las", "con", "sin",
    "por", "para", "en", "del", "fox", "rockshox", "xt", "gx", "xtr", "slx",
    "deore", "sram", "kashima", "axs", "ep8", "ep801", "ep6", "cx", "sx",
    "dos", "segunda", "mano", "vendo", "buen", "estado", "perfeto", "perfecto",
}


def _normalizar_ascii(texto: str) -> str:
    """Normaliza tildes y convierte a minúsculas conservando superíndices clave."""
    txt = (texto or "").replace("²", "2").lower()
    return "".join(
        c for c in unicodedata.normalize("NFD", txt)
        if unicodedata.category(c) != "Mn"
    )


def _detectar_contradiccion_nueva(bici: Bicicleta) -> bool:
    """Detecta contradicción cuando el anuncio dice NUEVA/ESTRENAR pero supera 50 km."""
    titulo_norm = _normalizar_ascii(bici.titulo)
    afirma_nueva = bool(re.search(r"\b(?:nueva|nuevo|a\s+estrenar|estrenar|km\s*0)\b", titulo_norm))
    if not afirma_nueva:
        return False
    es_matiz = bool(re.search(r"\b(?:como\s+nueva|casi\s+nueva|semi\s*nueva|seminueva|de\s+nuevo)\b", titulo_norm))
    if es_matiz:
        return False
    return bici.km is not None and bici.km > 50


def _es_anuncio_generico_sin_modelo(bici: Bicicleta) -> bool:
    """True si el anuncio carece de marca + modelo identificables (Línea Roja <= 4.5)."""
    titulo_norm = _normalizar_ascii(bici.titulo)
    if any(p in titulo_norm for entrada in CATALOGO_EMTB for p in entrada["patrones"]):
        return False
    if not _MARCAS_EMTB_RE.search(titulo_norm):
        return True
    if _MODELOS_IDENTIFICABLES_RE.search(titulo_norm):
        return False

    # Quitar marca, pesos/batería/años/tallas comunes y verificar si queda un token concreto de modelo
    sin_marca = _MARCAS_EMTB_RE.sub(" ", titulo_norm)
    tokens = re.findall(r"[a-z0-9\-\.]+", sin_marca)
    significativos = []
    for tok in tokens:
        t = tok.strip(".-")
        if not t or t in _STOPWORDS_MODELO_GENERICO:
            continue
        if re.fullmatch(r"(?:20\d\d|26|27\.?5|29|10v|11v|12v|\d+w|\d+wh|\d+nm|\d+mm|t\.?[sml]|s[1-6]|[xsml]{1,3})", t):
            continue
        if t.isdigit():
            continue
        if len(t) >= 2:
            significativos.append(t)
    return len(significativos) == 0


def _es_motor_full_power(motor: Optional[str], titulo: str = "") -> bool:
    """Identifica motores Full Power clásicos que superan 22.5 kg con baterías >= 625 Wh."""
    txt = _normalizar_ascii(f"{motor or ''} {titulo}")
    if any(k in txt for k in ("ep8 rs", "ep8-rs", "ep801 rs", "ep801-rs", "ep6 rs", "ep6-rs", "ep600 rs", "ep600-rs", "bosch sx", "performance line sx", "specialized sl", "tq", "fazua", "mahle", "2exmag")):
        return False
    return bool(
        re.search(
            r"\b(?:bosch(?:\s+performance(?:\s+line)?)?\s*cx|shimano\s+ep(?:801|8|6)|ep801|ep8|ep6|specialized\s*(?:2\.[12]|full\s*power)|brose(?:\s+s\s*mag)?|yamaha|pw-?x\d*|giant\s+syncdrive|syncdrive|dji\s+avinox(?:\s*m\d+)?|avinox(?:\s*m\d+)?|polini|bafang|oli|ananda|panasonic)\b",
            txt,
        )
    )


def _es_excepcion_ligera(bici: Bicicleta) -> bool:
    """Solo las familias ligeras explícitas pueden bajar de 21 kg con baterías >= 500 Wh."""
    txt = _normalizar_ascii(f"{bici.titulo or ''} {bici.motor or ''}")
    if any(k in txt for k in ("rise lt h", "berria mako", "mako hybrid", "ilynx 9.", "ilynx+ 9.", "amflow tl", "am flow tl")):
        return False
    bat = bici.bateria_wh
    if any(k in txt for k in ("mondraker neat", "mondraker dune", "pivot shuttle sl", "shuttle sl")):
        return bat is None or bat >= 500
    return bool(
        re.search(
            r"\b(?:orbea\s+)?rise\w*\b|\bilynx\s+(?:race|trail)\b|\bmoterra(?:\s+neo)?\s+sl\b|"
            r"\bamflow\s+pl\b|\blevo\s+sl\b|\bkenevo\s+sl\b|\bfuel[\s\-]*exe\b|"
            r"\bscott\s+lumen\b|\bbmc\s+fourstroke\b|\bwilier\s+urta\b|\burta\s+hybrid\b|"
            r"\bams\s+hybrid\b|\be-?zesty\b|\bvam\s*2(?:\s*sl)?\b|\bjam\s*2\s*sl\b|"
            r"\bmacina\s+scarp\b",
            txt,
        )
    )


def completar_con_catalogo(bici: Bicicleta, aplicar_heuristica_peso: bool = True) -> Bicicleta:
    """
    Completa campos faltantes de la bicicleta cruzando su título y datos actuales
    con el catálogo técnico y aplicando física realista y correcciones de motor.
    """
    texto = (
        f"{bici.titulo} {bici.motor or ''} {bici.componentes or ''}"
        .lower()
        .replace("²", "2")
    )

    # Detección de Range Extender en título o componentes
    if bici.range_extender_wh is None:
        extender = _extraer_range_extender(texto)
        if extender:
            bici.range_extender_wh = extender
            if bici.bateria_wh is not None and bici.bateria_wh <= 600:
                bici.bateria_wh += extender

    for entrada in CATALOGO_EMTB:
        if any(p in texto for p in entrada["patrones"]):
            if bici.peso_kg is None:
                bici.peso_kg = entrada["peso_kg"]
            if entrada.get("peso_kg") is not None:
                bici._peso_catalogo = True
            if bici.bateria_wh is None:
                base_bat = entrada["bateria_wh_default"]
                if bici.range_extender_wh is not None and base_bat <= 600:
                    bici.bateria_wh = base_bat + bici.range_extender_wh
                else:
                    bici.bateria_wh = base_bat
            if not bici.motor:
                bici.motor = entrada["motor"]
            if not bici.cuadro_material:
                bici.cuadro_material = entrada["cuadro_material"]
            if bici.suspension_trasera is None:
                bici.suspension_trasera = entrada["suspension_trasera"]
            if "scott lumen" in texto and bici.recorrido_mm == 140:
                # Cuadro Scott Lumen es 130 mm XC/Downcountry aunque monte horquilla de 140 mm
                bici.recorrido_mm = 130
            if bici.recorrido_mm is None and entrada.get("recorrido_mm") is not None:
                bici.recorrido_mm = entrada["recorrido_mm"]
            es_cat_xc = (entrada.get("recorrido_mm") or 999) <= cfg.RECORRIDO_MAX_XC_MM
            if not bici.modalidad or bici.modalidad.strip().lower() in ("light e-mtb", "light emtb"):
                bici.modalidad = entrada["modalidad"]
            elif not es_cat_xc:
                # Modelo explícitamente Trail/Enduro en catálogo nunca debe ocultarse tras etiqueta HTML ambigua
                bici.modalidad = entrada["modalidad"]
            elif bici.recorrido_mm is None or bici.recorrido_mm <= cfg.RECORRIDO_MAX_XC_MM:
                # En tiendas como Buhobike la categoría 'electricas-trail-dobles' contamina XC puros con 'Trail'
                bici.modalidad = entrada["modalidad"]
            if (
                not bici.componentes
                and entrada.get("componentes_default")
                and bici.km == 0
                and cfg.es_sitio_tienda_nueva(bici.sitio, bici.url, bici.titulo)
            ):
                bici.componentes = entrada["componentes_default"]
            break

    # Regla C — Corrección estricta de motores (ignora erratas HTML de tiendas)
    titulo_lower = bici.titulo.lower()
    es_ilynx_full_power = any(
        k in titulo_lower
        for k in (
            "ilynx+ dl",
            "ilynx plus dl",
            "ilynx+ nx",
            "ilynx plus nx",
            "ilynx+ enduro",
            "ilynx plus enduro",
            "ilynx+ sl",
            "ilynx plus sl",
        )
    )
    if ("ilynx+" in titulo_lower or "ilynx plus" in titulo_lower) and not es_ilynx_full_power:
        if "ep6" not in (bici.motor or "").lower():
            bici.motor = "Shimano EP801"
        if bici.peso_kg is not None and bici.peso_kg < 19.5:
            bici.peso_kg = 20.4
        bici.modalidad = "Trail (160mm)"
        if bici.recorrido_mm is None:
            bici.recorrido_mm = 160
    elif ("bh " in titulo_lower or "ilynx" in titulo_lower) and ("ilynx race" in titulo_lower or "ilynx trail" in titulo_lower or "ilynx" in titulo_lower):
        if "ilynx" in titulo_lower and not es_ilynx_full_power:
            bici.motor = "BH 2EXMAG"
        elif "atomx" in titulo_lower and (not bici.motor or "shimano" in bici.motor.lower()):
            bici.motor = "Brose S Mag"
    elif "atomx" in titulo_lower and (not bici.motor or "shimano" in bici.motor.lower()):
        bici.motor = "Brose S Mag"

    if "orbea rise" in titulo_lower:
        if bici.ano in (2021, 2022):
            bici.motor = "Shimano EP8-RS"
        elif bici.ano is not None and bici.ano >= 2025:
            bici.motor = "Shimano EP801-RS Gen2"
            if bici.peso_kg is not None and bici.peso_kg < 19.5 and (bici.bateria_wh or 0) >= 600:
                bici.peso_kg = 20.2

    # Cuadro aluminio vs carbono sin falsos positivos en español ('al 98%', 'al día')
    if not bici.cuadro_material:
        texto_raw_material = f"{bici.titulo or ''} {bici.componentes or ''}"
        if (
            re.search(r"\b(?:aluminio|aluminium|aluminum|alloy|alu)\b|\bh[123]0\b", texto)
            or re.search(
                r"\bAL\b(?!\s+(?:D[IÍ]A|CORRIENTE|100|MEJOR|PRECIO|TENER|SER|NO|QUE|CON|DE|LA|EL|LOS|LAS|UN|UNA)\b)",
                texto_raw_material,
            )
        ):
            bici.cuadro_material = "Aluminio"
        elif re.search(r"\b(?:carbon|carbono|cf|m10|m20|m-team)\b", texto):
            bici.cuadro_material = "Carbono"

    # Regla B — Física realista anti-optimismo
    if aplicar_heuristica_peso and bici.peso_kg is None:
        es_carbono = (bici.cuadro_material or "").lower() == "carbono"
        es_ligera = _es_excepcion_ligera(bici)
        es_full = _es_motor_full_power(bici.motor, bici.titulo)
        es_generico = _es_anuncio_generico_sin_modelo(bici)
        bat = bici.bateria_wh

        if es_generico and (es_full or (bat is not None and bat >= 625)):
            bici.peso_kg = 23.5
        elif es_full and not es_ligera and (bat is None or bat >= 600):
            bici.peso_kg = 23.5
        elif es_full and not es_ligera:
            bici.peso_kg = 23.0
        elif es_ligera and es_carbono and bat is not None and bat <= 560:
            bici.peso_kg = 19.2
        elif es_ligera and es_carbono:
            bici.peso_kg = 20.2
        elif es_ligera and bat is not None and bat <= 560:
            bici.peso_kg = 20.5
        else:
            bici.peso_kg = 23.0

    if not bici.modalidad and bici.peso_kg is not None and bici.peso_kg >= cfg.PESO_DESCARTE_KG:
        bici.modalidad = "Trail"

    return bici


# ---------------------------------------------------------------------------
# Paso 2: Auditoría Pericial Determinista (Perito Mecánico Senior)
# ---------------------------------------------------------------------------
def _fmt_delta(val: float) -> str:
    """Formatea un ajuste numérico de la rúbrica sin bonos positivos."""
    if abs(val) < 0.05:
        return "-0.0"
    return f"{val:.1f}"


def auditar_perito_mecanico(bici: Bicicleta) -> dict:
    """
    Aplica la Regla Maestra del Perito Mecánico Escéptico y Estricto (v2):
      Parte de BASE = 10.0 sin bonos positivos y aplica 5 ejes matemáticos + Líneas Rojas:
        - Talla != M -> Cap 0.0 (DESCARTADA)
        - Batería < 500 Wh -> Cap 4.0 (DESCARTADA)
        - Peso > 21.0 kg -> Cap 4.0 (DESCARTADA)
        - Kilometraje > 6.000 km -> Cap 4.5 (DESCARTADA)
        - Anuncio genérico sin marca ni modelo identificable -> Cap 4.5 (DESCARTADA)
    """
    base = 10.0
    techo = 10.0
    lineas_rojas = []

    km = bici.km
    peso = bici.peso_kg
    precio = bici.precio
    contradiccion_nueva = _detectar_contradiccion_nueva(bici)
    es_generico = _es_anuncio_generico_sin_modelo(bici)

    # 1) KILOMETRAJE Y DESGASTE
    if km is not None and km > 6000:
        delta_km = -4.5
        techo = min(techo, 4.5)
        lineas_rojas.append("Km >6.000 (máx 4.5)")
        txt_km = (
            f"{km} km (-4.5 pts -> LÍNEA ROJA 4.5 DESCARTADA): "
            f"Desgaste severo acumulado en celdas de batería, rodamientos de motor, casete, platos y basculante."
        )
    elif km is None:
        delta_km = -2.0
        txt_km = (
            "NO ESPECIFICADO (-2.0 pts preventivos). Posible coste oculto de 250-450 € en transmisión, "
            "pastillas y servicio de suspensiones; exigir lectura de odómetro antes de comprar."
        )
    elif km <= 1000:
        delta_km = 0.0
        txt_km = (
            f"{km} km (-0.0 pts, rango 0-1.000 km): Uso mínimo sin contradicciones; "
            f"desgaste bajo en cadena, discos y retenes."
        )
    elif km <= 2000:
        delta_km = -1.0
        txt_km = (
            f"{km} km (-1.0 pt, rango 1.001-2.000 km): Rodaje moderado; "
            f"prever sustitución preventiva de cadena y pastillas (80-150 €)."
        )
    elif km <= 4000:
        delta_km = -2.5
        txt_km = (
            f"{km} km (-2.5 pts, rango 2.001-4.000 km): Desgaste medio en transmisión 12v, "
            f"retenes de horquilla/amortiguador y rodamientos de bieleta (200-350 €)."
        )
    else:
        delta_km = -3.5
        txt_km = (
            f"{km} km (-3.5 pts, rango 4.001-6.000 km): Mantenimiento mayor inminente "
            f"(transmisión completa, retenes, rodamientos de basculante/motor: 300-500 €)."
        )

    if contradiccion_nueva and km is not None:
        # La contradicción ('NUEVA' + >50 km) penaliza mínimo -2.0 sin suavizar tramos altos
        delta_km = min(delta_km, -2.0)
        txt_km = (
            f"CONTRADICCIÓN ('NUEVA' declarada con {km} km reales > 50 km -> {delta_km:.1f} pts). "
            + txt_km
        )

    # 2) PESO REAL ESTIMADO
    if peso is None:
        delta_peso = 0.0
        txt_peso = (
            f"Peso NO ESPECIFICADO (chasis {bici.cuadro_material or 'NO ESPECIFICADO'}; -0.0 pts en espera de pesaje real)."
        )
    elif peso <= 19.0:
        delta_peso = 0.0
        txt_peso = (
            f"{peso} kg (-0.0 pts, <=19.0 kg): Peso ligero real para chasis {bici.cuadro_material or 'ligero'}, "
            f"menor estrés dinámico en frenos y suspensiones."
        )
    elif peso <= 20.0:
        delta_peso = -0.5
        txt_peso = (
            f"{peso} kg (-0.5 pts, rango 19.1-20.0 kg): Peso contenido en orden de marcha "
            f"({bici.cuadro_material or 'cuadro no especificado'} / {bici.bateria_wh or '?'} Wh)."
        )
    elif peso <= 21.0:
        delta_peso = -1.5
        txt_peso = (
            f"{peso} kg (-1.5 pts, rango 20.1-21.0 kg): Al filo del límite de 21.0 kg; "
            f"mayor inercia en sendero y desgaste acelerado de pastillas/neumáticos."
        )
    else:
        delta_peso = -6.0
        techo = min(techo, 4.0)
        lineas_rojas.append("Peso >21.0 kg (máx 4.0)")
        txt_peso = (
            f"{peso} kg (-6.0 pts -> LÍNEA ROJA 4.0 DESCARTADA): "
            f"Supera el tope de 21.0 kg en orden de marcha para chasis/motor/batería ({bici.bateria_wh or '?'} Wh)."
        )

    # 3) MOTOR, DIAGNOSIS Y BATERÍA
    motor_str = bici.motor or ""
    motor_lower = motor_str.lower()
    titulo_lower = bici.titulo.lower()

    es_ilynx_plus = "ilynx+" in titulo_lower or "ilynx plus" in titulo_lower
    es_bh_sin_plus = (
        not es_ilynx_plus
        and (
            "2exmag" in motor_lower
            or "2esmag" in motor_lower
            or "ilynx" in titulo_lower
            or "atomx" in titulo_lower
        )
    )
    es_bosch = "bosch" in motor_lower or "bosch" in titulo_lower
    es_shimano_auditable = (
        not es_bh_sin_plus
        and (
            es_ilynx_plus
            or "shimano" in motor_lower
            or "ep8" in motor_lower
            or "ep6" in motor_lower
            or "orbea rise" in titulo_lower
        )
    )
    es_specialized_auditable = (
        "specialized" in motor_lower
        or "levo" in titulo_lower
        or "kenevo" in titulo_lower
    )

    salud_pct = getattr(bici, "bateria_salud_pct", None)
    ciclos_bat = getattr(bici, "bateria_ciclos", None)
    bat = bici.bateria_wh
    extender = getattr(bici, "range_extender_wh", None)
    extender_str = f" [incluye Range Extender oficial de {extender} Wh]" if extender else ""

    if bat is not None and bat < 500:
        techo = min(techo, 4.0)
        lineas_rojas.append(f"Batería <500 Wh ({bat} Wh, máx 4.0)")

    # Penalización base de diagnóstico por familia de motor
    if es_bh_sin_plus:
        motor_real_txt = "BH 2EXMAG" if "ilynx" in titulo_lower else (bici.motor or "Propietario BH / Brose S Mag")
        delta_motor_base = -0.5 if (km is not None and km <= 2000) else -1.0
        txt_audit = (
            f"Sistema cerrado {motor_real_txt} ({delta_motor_base:.1f} pts): no permite auditoría PDF abierta de SoH ni ciclos"
        )
    elif es_bosch:
        motor_real_txt = bici.motor or "Bosch Performance CX/SX"
        if salud_pct is not None and ciclos_bat is not None:
            delta_motor_base = 0.0
            txt_audit = f"{motor_real_txt} con informe oficial completo ({salud_pct}% SoH, {ciclos_bat} ciclos: -0.0 pts)"
        else:
            delta_motor_base = -0.5
            txt_audit = (
                f"{motor_real_txt} (-0.5 pts): Bosch NO muestra ciclos ni SoH químico en la app de usuario; requiere taller oficial"
            )
    elif es_shimano_auditable:
        motor_real_txt = bici.motor or ("Shimano EP801" if es_ilynx_plus else "Shimano EP8/EP801/EP6")
        delta_motor_base = 0.0
        txt_audit = f"{motor_real_txt} (abierto y auditable vía E-Tube/app: -0.0 pts)"
    elif es_specialized_auditable:
        motor_real_txt = bici.motor or "Specialized Turbo"
        delta_motor_base = 0.0
        txt_audit = f"{motor_real_txt} (auditable vía Turbo Studio / app propia: -0.0 pts)"
    else:
        motor_real_txt = bici.motor or "NO ESPECIFICADO (sistema cerrado o desconocido)"
        delta_motor_base = -0.5 if (km is not None and km <= 2000) else -1.0
        txt_audit = f"{motor_real_txt} (sistema cerrado/sin app abierta: {delta_motor_base:.1f} pts)"

    # Penalización extra (-0.5) si NO aporta SoH/ciclos y tiene > 1.500 km o km desconocidos
    sin_soh_ni_ciclos = salud_pct is None and ciclos_bat is None
    if sin_soh_ni_ciclos and (km is None or km > 1500):
        delta_soh_extra = -0.5
        txt_soh = "Sin informe de SoH/ciclos con >1.500 km o km desconocidos (-0.5 pts extra)."
    elif salud_pct is not None or ciclos_bat is not None:
        delta_soh_extra = 0.0
        partes_soh = []
        if salud_pct is not None:
            partes_soh.append(f"SoH medido: {salud_pct}%")
        if ciclos_bat is not None:
            partes_soh.append(f"{ciclos_bat} ciclos diagnosticados")
        alerta_soh = " ⚠️ ALERTA CRÍTICA: degradación severa de celdas (<80%)." if (salud_pct is not None and salud_pct < 80) else ""
        txt_soh = f"Telemetría aportada ({' | '.join(partes_soh)}).{alerta_soh}"
    else:
        delta_soh_extra = 0.0
        txt_soh = "SoH/ciclos NO ESPECIFICADOS (riesgo contenido por <=1.500 km declarados)."

    delta_motor = round(delta_motor_base + delta_soh_extra, 2)
    bat_label = f"{bat} Wh{extender_str}" if bat is not None else "Batería NO ESPECIFICADA"
    txt_motor = f"{txt_audit}. {bat_label}. {txt_soh}"

    # 4) GARANTÍA Y CANAL DE VENTA
    garantia_bici = getattr(bici, "garantia_anos", None)
    url_lower = (bici.url or "").lower()
    es_extranjera = bool(
        re.search(r"alltricks|bikester|rebike|bike24|probikeshop|upway\.(?:de|fr|it)", url_lower)
    )
    if es_extranjera:
        delta_garantia = -1.0
        txt_garantia = (
            f"Tienda extranjera ({bici.sitio}, -1.0 pt): gestión compleja de devoluciones y garantías fuera de España."
        )
    elif garantia_bici == 0:
        texto_fact = f"{bici.titulo or ''} {bici.componentes or ''}".lower()
        menciona_factura = bool(
            getattr(bici, "tiene_factura", False)
            or (
                re.search(r"\bfactura\b", texto_fact)
                and not re.search(r"\bsin\s+factura\b", texto_fact)
            )
        )
        factura_vigente = menciona_factura and (
            bici.ano is None or (datetime.now().year - bici.ano) <= 2
        )
        if factura_vigente:
            delta_garantia = -1.0
            txt_garantia = (
                "Particular en Wallapop con factura (< 2 años, -1.0 pt): cobertura legal parcial de fabricante, sin garantía comercial de tienda."
            )
        else:
            delta_garantia = -1.5
            txt_garantia = (
                "Particular sin garantía comercial ni mención de factura vigente (-1.5 pts): riesgo íntegro asumido por el comprador."
            )
    else:
        delta_garantia = 0.0
        anos_g = garantia_bici if garantia_bici is not None else 1
        txt_garantia = (
            f"Tienda profesional en España ({bici.sitio}, {anos_g} año(s) de garantía legal, -0.0 pts): riesgo de canal cubierto."
        )

    # 5) PRECIO Y COMPONENTES
    if precio <= 3000:
        delta_precio_tramo = 0.0
        txt_p_tramo = f"Precio {precio:.0f} € en rango objetivo 2.000-3.000 € (-0.0 pts)."
    elif precio <= 3150:
        delta_precio_tramo = -0.5
        txt_p_tramo = f"Precio {precio:.0f} € en margen negociable 3.001-3.150 € (-0.5 pts)."
    else:
        delta_precio_tramo = -2.0
        txt_p_tramo = f"Precio {precio:.0f} € supera los 3.150 € (-2.0 pts)."

    texto_comp_raw = f"{bici.componentes or ''} {bici.titulo or ''}".lower()
    patron_comp_detallado = (
        r"\b(?:xt|slx|xtr|deore|gx|x0|x01|xx1|nx|sx|eagle|axs|cues|alivio|acera|altus|"
        r"fox(?:\s*(?:32|34|36|38|float|rhythm|performance|factory))?|rock\s*shox|marzocchi|ohlins|manitou|"
        r"sr\s*suntour|suntour|magura|hope|mt\d{3}|12v|11v|10v|kashima|factory|ultimate|pike|lyrik|sid|zeb|recon|judy)\b"
    )
    comp_val = (bici.componentes or "").strip().lower()
    comp_es_vacio = comp_val in ("", "de serie", "no indicado", "no especificado", "estándar", "estandar")
    tiene_comp_detallados = bool(
        (not comp_es_vacio and re.search(patron_comp_detallado, comp_val))
        or re.search(patron_comp_detallado, (bici.titulo or "").lower())
        or (not comp_es_vacio and len(comp_val) >= 12)
    )

    if not tiene_comp_detallados:
        delta_comp = -1.5
        txt_comp = "Componentes principales (horquilla/transmisión/frenos) NO ESPECIFICADOS en el anuncio (-1.5 pts)."
    elif precio > 2400:
        rasgos_basicos = 0
        if re.search(r"\b(?:10v|11v|acera|alivio|altus)\b", texto_comp_raw):
            rasgos_basicos += 1
        if re.search(r"\b(?:mt200|mt400|mt401)\b", texto_comp_raw):
            rasgos_basicos += 1
        if re.search(r"\b(?:suntour\s*xcm|suntour\s*xct|suntour\s*xcr|judy\s*silver)\b", texto_comp_raw):
            rasgos_basicos += 1

        if rasgos_basicos >= 2:
            delta_comp = -1.0
            txt_comp = f"Montaje básico/obsoleto ({bici.componentes or 'declarado'}) costando >2.400 € (-1.0 pt)."
        elif rasgos_basicos == 1:
            delta_comp = -0.5
            txt_comp = f"Componente de acceso (10v/11v/frenos básicos o horquilla básica) costando >2.400 € (-0.5 pts)."
        else:
            delta_comp = 0.0
            txt_comp = f"Montaje declarado acorde ({bici.componentes or 'declarado'}): -0.0 pts."
    else:
        delta_comp = 0.0
        txt_comp = f"Montaje declarado ({bici.componentes or 'declarado'}) correcto para {precio:.0f} €: -0.0 pts."

    if extender:
        txt_comp += f" Nota adicional: incluye Range Extender oficial (+{extender} Wh)."

    delta_precio = round(delta_precio_tramo + delta_comp, 2)
    txt_precio = f"{txt_p_tramo} {txt_comp}"

    # Resto de Líneas Rojas (Talla != M -> 0.0, Anuncio genérico -> 4.5)
    talla_norm = (bici.talla or "").strip().upper()
    if talla_norm and talla_norm not in ("M", "NO INDICADA"):
        techo = min(techo, 0.0)
        lineas_rojas.append(f"Talla != M ({bici.talla}, máx 0.0)")

    if es_generico:
        techo = min(techo, 4.5)
        lineas_rojas.append("Anuncio genérico sin marca/modelo (máx 4.5)")

    nota_aritmetica = base + delta_km + delta_peso + delta_motor + delta_garantia + delta_precio
    nota_final = round(max(0.0, min(10.0, nota_aritmetica, techo)), 2)

    pvp_orig = getattr(bici, "pvp_original", None)
    if pvp_orig and pvp_orig > precio > 0:
        dto_pvp = ((pvp_orig - precio) / pvp_orig) * 100.0
        if dto_pvp >= 50.0:
            if nota_final >= 9.0:
                txt_precio += f" ¡Mega Chollo certificado! Nota {nota_final}/10 con -{dto_pvp:.0f}% vs PVP ({pvp_orig:.0f} €)."
            else:
                txt_precio += f" Descuento del {dto_pvp:.0f}% respecto a PVP ({pvp_orig:.0f} €)."

    cap_txt = f"Sí ({', '.join(lineas_rojas)})" if lineas_rojas else "No"
    formula_str = (
        f"Base 10.0 {_fmt_delta(delta_km)} (Km) {_fmt_delta(delta_peso)} (Peso) "
        f"{_fmt_delta(delta_motor)} (Motor/Bat) {_fmt_delta(delta_garantia)} (Garantía) "
        f"{_fmt_delta(delta_precio)} (Precio/Comp) = {nota_aritmetica:.1f} -> "
        f"Cap Línea Roja: {cap_txt} => {nota_final}/10"
    )

    return {
        "nota_final": nota_final,
        "nota_aritmetica": round(nota_aritmetica, 2),
        "techo": techo,
        "lineas_rojas": lineas_rojas,
        "delta_km": delta_km,
        "delta_peso": delta_peso,
        "delta_motor": delta_motor,
        "delta_garantia": delta_garantia,
        "delta_precio": delta_precio,
        "formula_str": formula_str,
        "txt_km": txt_km,
        "txt_peso": txt_peso,
        "txt_motor": txt_motor,
        "txt_bateria": txt_motor,
        "txt_garantia": txt_garantia,
        "txt_precio": txt_precio,
    }


def valorar_autonomo(bici: Bicicleta) -> Tuple[float, str]:
    """
    Calcula la nota de oportunidad (0.0 a 10.0) y genera la auditoría técnica
    del Perito Mecánico Escéptico en el formato obligatorio de 5 ejes.
    """
    audit = auditar_perito_mecanico(bici)
    desglose = (
        f"🧮 Auditoría Pericial: {audit['formula_str']}\n"
        f"• 🛣️ Km: {audit['txt_km']}\n"
        f"• ⚖️ Peso: {audit['txt_peso']}\n"
        f"• 🔍 Motor y Batería: {audit['txt_motor']}\n"
        f"• 🛡️ Garantía y Vendedor: {audit['txt_garantia']}\n"
        f"• 💰 Precio/Componentes: {audit['txt_precio']}"
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
        gen_cfg: dict = {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        }
        if "3-flash" in model:
            gen_cfg["thinkingConfig"] = {"thinkingBudget": 0}
        payload: dict = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": gen_cfg,
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
    # 1. Enriquecimiento desde la ficha HTML del sitio (o galería Wallapop sin DuckDuckGo aún)
    try:
        bici = enriquecer_bici(bici, url_ficha=bici.url, usar_duckduckgo=False)
    except Exception as e:
        log.warning(f"[IA] Error en enriquecer_bici para {bici.titulo}: {e}")

    peso_despues_web = bici.peso_kg

    # 2. Enriquecimiento desde catálogo técnico local antes de consultar DuckDuckGo
    bici = completar_con_catalogo(bici, aplicar_heuristica_peso=False)
    peso_tras_cat = bici.peso_kg

    # Cortocircuito antes de DuckDuckGo/Gemini si tras enriquecer ya hay rechazo duro (sin stock, talla != M o no doble)
    talla_upper = (bici.talla or "").strip().upper()
    es_talla_descartada = bool(talla_upper and talla_upper not in (cfg.TALLA_OBJETIVO.upper(), "NO INDICADA"))
    es_no_doble = (
        bici.suspension_trasera is not None
        and str(bici.suspension_trasera).strip().lower() in ("false", "no", "0")
    )
    if getattr(bici, "disponible", True) is False or es_talla_descartada or es_no_doble:
        bici = completar_con_catalogo(bici, aplicar_heuristica_peso=True)
        if peso_despues_web is None and bici.peso_kg is not None:
            bici._peso_estimado = True
        nota_fast, desglose_fast = valorar_autonomo(bici)
        log.info(
            f"[Perito Rápido] {bici.titulo} -> {nota_fast}/10 "
            f"(disp={getattr(bici, 'disponible', True)}, talla={bici.talla}, doble={bici.suspension_trasera})"
        )
        return bici, nota_fast, desglose_fast

    # 2b. Fallback DuckDuckGo cacheado solo si el catálogo tampoco cubrió peso/suspensión/año
    try:
        bici = completar_desde_duckduckgo(bici)
    except Exception as e:
        log.warning(f"[IA] Error en DuckDuckGo para {bici.titulo}: {e}")

    # Peso empírico verificado desde el anuncio o DuckDuckGo (catálogo estático / Regla B / Gemini son estimaciones)
    ddg_aporto_peso = bici.peso_kg is not None and bici.peso_kg != peso_tras_cat
    peso_empirico_previo = bici.peso_kg if (peso_despues_web is not None or ddg_aporto_peso) else None

    # Verificar caché de valoración IA (perito_v6_xc: XC <= 130 mm estricto)
    cache_version = "perito_v6_xc"
    cache_key = f"{cache_version}:{bici.sitio}:{bici.bici_id}:{int(bici.precio)}"
    pvp_actual_int = int(getattr(bici, "pvp_original", 0) or 0)
    cache_ia = _cargar_cache_ia()
    if cache_key in cache_ia:
        entry = cache_ia[cache_key]
        km_cambio = entry.get("km") != bici.km
        peso_corregido = (bici.peso_kg is not None and entry.get("peso_kg") != bici.peso_kg)
        pvp_cambio = ("pvp_original_int" in entry and entry.get("pvp_original_int") != pvp_actual_int)
        if not km_cambio and not peso_corregido and not pvp_cambio:
            for campo in ("talla", "modalidad", "peso_kg", "bateria_wh", "range_extender_wh",
                          "bateria_salud_pct", "bateria_ciclos", "cuadro_material",
                          "motor", "ano", "componentes", "suspension_trasera", "recorrido_mm"):
                if entry.get(campo) is not None and getattr(bici, campo, None) is None:
                    setattr(bici, campo, entry[campo])
            bici = completar_con_catalogo(bici, aplicar_heuristica_peso=True)
            if peso_empirico_previo is None and bici.peso_kg is not None:
                bici._peso_estimado = True
            audit_cached = auditar_perito_mecanico(bici)
            return bici, audit_cached["nota_final"], str(entry["desglose"])
        log.info(
            f"[Caché IA] Invalidando entrada de {bici.titulo} por actualización de km/peso/pvp "
            f"(km {entry.get('km')} -> {bici.km}, pvp {entry.get('pvp_original_int')} -> {pvp_actual_int})"
        )

    # Pre-auditoría con los datos conocidos hasta ahora
    audit_pre = auditar_perito_mecanico(bici)
    peso_antes_gemini = bici.peso_kg
    comp_antes_gemini = bici.componentes

    garantia_prompt = (
        f"Particular en {bici.sitio} CON factura mencionada"
        if (getattr(bici, "garantia_anos", None) == 0 and getattr(bici, "tiene_factura", False))
        else (
            "Particular sin garantía comercial ni mención de factura"
            if getattr(bici, "garantia_anos", None) == 0
            else f"Tienda profesional ({bici.sitio}, {getattr(bici, 'garantia_anos', 1) or 1} año(s) garantía legal)"
        )
    )

    # 3. Clasificación y auditoría con Gemini Flash bajo el prompt de Perito Mecánico Escéptico y Estricto
    prompt = f"""Eres un perito mecánico escéptico y estricto especializado en e-MTBs de segunda mano. Tu trabajo NO es buscar excusas para aprobar bicis, sino proteger el dinero del comprador detectando falsos positivos, pesos irreales, erratas de catalogación y desgastes ocultos.

REQUISITOS DEL COMPRADOR:
- Talla: M (o altura 165-179 cm).
- Peso real en orden de marcha: < 21.0 kg (objetivo ideal: < 19.5 kg).
- Batería interna: >= 500 Wh.
- Presupuesto objetivo: 2.000 € - 3.000 € (margen negociable máx. 3.150 €).
- Modalidad obligatoria: ESTRICTAMENTE XC / Cross Country / Downcountry ligero (<= 130 mm de recorrido; DESCARTAR Trail >= 140 mm como Orbea Rise, BH iLynx Trail, Cannondale Moterra SL, Ghost Path Riot, Levo SL, Trek Fuel EXe, Mondraker Neat, All Mountain o Enduro).

==================================================
1. REGLAS ANTI-ALUCINACIÓN (OBLIGATORIAS)
==================================================
A) PROHIBIDO INVENTAR DATOS:
- Nunca asumas "buenos componentes" si el anuncio no especifica marca, modelo, horquilla y transmisión.
- Si un dato no aparece en el texto (km, año, salud batería, marca, componentes), márcalo como "NO ESPECIFICADO" y aplica su penalización.
- Si el título dice "NUEVA" pero el kilometraje es > 50 km, trátalo como CONTRADICCIÓN y penalízalo.

B) FÍSICA REALISTA DE PESO (ANTI-OPTIMISMO):
- NUNCA estimes menos de 22.5 kg para una e-MTB de doble suspensión con motor Full Power clásico (Bosch Performance Line CX, Shimano EP8/EP801 Full Power, Brose S Mag, Yamaha PW-X, Giant SyncDrive) + batería >= 625 Wh, aunque sea de carbono. Asigna 23.0-24.5 kg por defecto.
- ÚNICAS EXCEPCIONES ligeras (< 21 kg con >= 500 Wh): Orbea Rise (H 540Wh: ~20.5 kg; M/LT/SL 2025-2026 630Wh: ~19.5-20.6 kg), BH iLynx Race/Trail Carbon (540Wh: ~18.3-19.5 kg), Cannondale Moterra SL (601Wh: ~19.8 kg), Amflow PL Carbon (600/800Wh: ~19.5-21.0 kg), Mondraker Neat/Dune o Pivot Shuttle SL solo si llevan batería >= 500 Wh.
- Si el anuncio NO indica marca ni modelo exacto y lleva motor Full Power + >= 625 Wh -> asume obligatoriamente >= 23.5 kg.

C) CORRECCIÓN DE MOTOR (IGNORA ERRATAS HTML DE TIENDAS):
- "BH iLynx Race" o "BH iLynx Trail" (SIN el símbolo "+" de 2024+): motor SIEMPRE = "BH 2EXMAG" (sistema cerrado, aunque la web diga Shimano).
- "BH iLynx+" (CON símbolo "+"): motor = "Shimano EP801" (abierto).
- "Orbea Rise 2021-2022": motor = "Shimano EP8-RS" (60 Nm). "Rise 2025+": "Shimano EP801-RS Gen2" (hasta 85 Nm).
- Recuerda: Bosch NO muestra ciclos ni salud química (SoH) en la app de usuario; requiere interfaz de taller oficial.

==================================================
2. LÍNEAS ROJAS ELIMINATORIAS (CAP DE NOTA FINAL)
==================================================
Calcula primero la nota matemática y, al final, aplica el tope más bajo que se active:
- Talla distinta de M (S, L, XL): NOTA MÁXIMA = 0.0 (DESCARTADA).
- Batería < 500 Wh (ej. 360 Wh, 400 Wh): NOTA MÁXIMA = 4.0 (DESCARTADA).
- Peso real o estimado > 21.0 kg: NOTA MÁXIMA = 4.0 (DESCARTADA).
- Kilometraje > 6.000 km: NOTA MÁXIMA = 4.5 (DESCARTADA).
- Anuncio genérico sin marca ni modelo identificable: NOTA MÁXIMA = 4.5 (DESCARTADA).
- Modalidad Trail / All Mountain / Enduro (>= 140 mm): NOTA MÁXIMA = 3.0 (DESCARTADA por no ser XC <= 130 mm).

==================================================
3. RÚBRICA MATEMÁTICA DE 5 EJES (BASE = 10.0)
==================================================
Aplica estrictamente estas restas (no sumes bonos positivos):

1) KILOMETRAJE Y DESGASTE:
- 0 a 1.000 km (verificados sin contradicciones): 0.0
- 1.001 a 2.000 km: -1.0
- 2.001 a 4.000 km: -2.5
- 4.001 a 6.000 km: -3.5
- > 6.000 km: -4.5 (activa Línea Roja 4.5)
- No especificado o contradictorio ("Nueva" + km > 50): -2.0

2) PESO REAL ESTIMADO:
- <= 19.0 kg: 0.0
- 19.1 a 20.0 kg: -0.5
- 20.1 a 21.0 kg: -1.5
- > 21.0 kg: -6.0 (activa Línea Roja 4.0)

3) MOTOR, DIAGNOSIS Y BATERÍA:
- Shimano EP8/EP801/EP6 o Specialized (auditables con app propia o PDF adjunto): 0.0
- Bosch Performance CX/SX sin informe PDF adjunto (requiere taller para ver ciclos/SoH): -0.5
- Motor propietario cerrado (BH 2EXMAG, Brose antiguo, otros): -0.5 (si <= 2.000 km) o -1.0 (si > 2.000 km)
- Penalización extra si NO aporta SoH/ciclos y tiene > 1.500 km (o km desconocidos): -0.5

4) GARANTÍA Y CANAL DE VENTA:
- Tienda profesional en España (>= 1 año garantía legal): 0.0
- Tienda extranjera / sin reseñas verificadas: -1.0
- Particular con factura vigente (< 2 años desde compra): -1.0
- Particular sin garantía comercial ni mención de factura: -1.5

5) PRECIO Y COMPONENTES:
- 2.000 € - 3.000 € con transmisión 12v (SLX/XT/GX) y suspensiones gama media-alta: 0.0
- Precio 3.001 € - 3.150 € (margen negociable): -0.5
- Precio > 3.150 €: -2.0
- Montaje básico/obsoleto (10v/11v, frenos entrada MT200/MT401, horquilla básica) costando > 2.400 €: -0.5 a -1.0
- Componentes principales no detallados en el anuncio: -1.5

Datos extraídos del anuncio ({bici.sitio} | URL: {bici.url}):
- Título: {bici.titulo}
- Precio: {bici.precio} €
- Talla: {bici.talla or 'NO ESPECIFICADO'}
- Peso conocido (kg): {bici.peso_kg if bici.peso_kg is not None else 'NO ESPECIFICADO (aplica física realista anti-optimismo)'}
- Batería (Wh): {bici.bateria_wh if bici.bateria_wh is not None else 'NO ESPECIFICADO'}
- Salud batería medida (SoH %): {f'{bici.bateria_salud_pct}%' if bici.bateria_salud_pct is not None else 'NO ESPECIFICADO'}
- Ciclos batería medidos: {bici.bateria_ciclos if bici.bateria_ciclos is not None else 'NO ESPECIFICADO'}
- Range Extender: {f'{bici.range_extender_wh} Wh incluido' if bici.range_extender_wh else 'no incluido / no detectado'}
- Motor: {bici.motor or 'NO ESPECIFICADO (aplica corrección de modelo si aplica)'}
- Cuadro: {bici.cuadro_material or 'NO ESPECIFICADO'}
- Kilómetros: {bici.km if bici.km is not None else 'NO ESPECIFICADO'}
- Año: {bici.ano if bici.ano is not None else 'NO ESPECIFICADO'}
- Componentes declarados: {bici.componentes or 'NO ESPECIFICADO'}
- Garantía/Canal: {garantia_prompt}
- Auditoría preliminar: {audit_pre['formula_str']}

Verifica la aritmética antes de responder y devuelve ÚNICAMENTE un objeto JSON válido con esta estructura exacta:
{{
  "peso_kg": numero_float_peso_real_o_null,
  "bateria_wh": numero_int_wh_o_null,
  "motor": "motor real corregido o NO ESPECIFICADO",
  "cuadro_material": "Carbono, Aluminio o NO ESPECIFICADO",
  "suspension_trasera": "si o no",
  "modalidad": "XC / Downcountry / Trail / Enduro",
  "recorrido_mm": numero_int_mm_suspension_delantera_o_null,
  "ano": numero_int_ano_o_null,
  "componentes": "solo componentes explícitamente declarados o NO ESPECIFICADO",
  "nota": numero_float_de_0_a_10,
  "km_analisis": "Explicación concreta de km, contradicciones y costes de mantenimiento previsibles",
  "peso_analisis": "Peso real estimado justificado por chasis/motor/batería; sin optimismo",
  "motor_bateria_analisis": "Motor real corregido, facilidad real de auditoría y riesgo de batería",
  "garantia_analisis": "Canal, cobertura real y nivel de riesgo",
  "precio_componentes_analisis": "Valoración estricta solo de los componentes declarados"
}}"""

    res_gemini = _llamar_gemini_api(prompt, usar_busqueda=False)
    if res_gemini:
        try:
            if bici.peso_kg is None and res_gemini.get("peso_kg"):
                bici.peso_kg = float(res_gemini["peso_kg"])
            if bici.bateria_wh is None and res_gemini.get("bateria_wh"):
                bici.bateria_wh = int(res_gemini["bateria_wh"])
            if not bici.motor and res_gemini.get("motor"):
                m_gem = str(res_gemini["motor"]).strip()
                if "no especificado" not in m_gem.lower():
                    bici.motor = m_gem
            if not bici.cuadro_material and res_gemini.get("cuadro_material"):
                c_gem = str(res_gemini["cuadro_material"]).strip()
                if "no especificado" not in c_gem.lower():
                    bici.cuadro_material = c_gem
            if bici.suspension_trasera is None and res_gemini.get("suspension_trasera"):
                bici.suspension_trasera = str(res_gemini["suspension_trasera"]).lower()
            if not bici.modalidad and res_gemini.get("modalidad"):
                bici.modalidad = str(res_gemini["modalidad"])
            if bici.recorrido_mm is None and res_gemini.get("recorrido_mm") is not None:
                m_rec = re.search(r"\b(\d{2,3})\b", str(res_gemini["recorrido_mm"]))
                if m_rec:
                    bici.recorrido_mm = int(m_rec.group(1))
            if bici.ano is None and res_gemini.get("ano"):
                bici.ano = int(res_gemini["ano"])
            if not comp_antes_gemini and res_gemini.get("componentes"):
                comp_gem = str(res_gemini["componentes"]).strip()
                if (
                    comp_gem
                    and "no especificado" not in comp_gem.lower()
                    and "no detallado" not in comp_gem.lower()
                    and not _es_anuncio_generico_sin_modelo(bici)
                ):
                    bici.componentes = comp_gem

            bici = completar_con_catalogo(bici, aplicar_heuristica_peso=True)

            # Blindaje anti-optimismo post-Gemini (Regla B): Full Power (>=625Wh o bat desconocida) nunca < 22.5 kg
            if (
                peso_antes_gemini is None
                and bici.peso_kg is not None
                and bici.peso_kg < 22.5
                and not _es_excepcion_ligera(bici)
                and (
                    (_es_motor_full_power(bici.motor, bici.titulo) and (bici.bateria_wh is None or bici.bateria_wh >= 625))
                    or (_es_anuncio_generico_sin_modelo(bici) and (_es_motor_full_power(bici.motor, bici.titulo) or (bici.bateria_wh or 0) >= 625))
                )
            ):
                bici.peso_kg = 23.5

            # Re-auditar matemáticamente con los campos definitivos (garantiza aritmética y caps exactos)
            audit_post = auditar_perito_mecanico(bici)
            nota_final = audit_post["nota_final"]

            desglose_ia = (
                f"🧮 Auditoría Pericial: {audit_post['formula_str']}\n"
                f"• 🛣️ Km: {res_gemini.get('km_analisis', audit_post['txt_km'])}\n"
                f"• ⚖️ Peso: {res_gemini.get('peso_analisis', audit_post['txt_peso'])}\n"
                f"• 🔍 Motor y Batería: {res_gemini.get('motor_bateria_analisis', audit_post['txt_motor'])}\n"
                f"• 🛡️ Garantía y Vendedor: {res_gemini.get('garantia_analisis', audit_post['txt_garantia'])}\n"
                f"• 💰 Precio/Componentes: {res_gemini.get('precio_componentes_analisis', audit_post['txt_precio'])}"
            )

            entry_data = {
                "talla": bici.talla,
                "modalidad": bici.modalidad,
                "peso_kg": bici.peso_kg,
                "bateria_wh": bici.bateria_wh,
                "range_extender_wh": bici.range_extender_wh,
                "bateria_salud_pct": bici.bateria_salud_pct,
                "bateria_ciclos": bici.bateria_ciclos,
                "cuadro_material": bici.cuadro_material,
                "motor": bici.motor,
                "km": bici.km,
                "ano": bici.ano,
                "pvp_original_int": pvp_actual_int,
                "componentes": bici.componentes,
                "suspension_trasera": bici.suspension_trasera,
                "recorrido_mm": bici.recorrido_mm,
                "nota": nota_final,
                "desglose": desglose_ia,
            }
            _guardar_entrada_cache_ia(cache_key, entry_data)
            if peso_empirico_previo is None and bici.peso_kg is not None:
                bici._peso_estimado = True
            log.info(
                f"[Perito IA] {bici.titulo} -> {nota_final}/10 "
                f"(km={bici.km}, peso={bici.peso_kg} kg) | {audit_post['formula_str']}"
            )
            return bici, nota_final, desglose_ia
        except Exception as e:
            log.warning(f"[Gemini Flash] Error procesando respuesta JSON para {bici.titulo}: {e}")

    # 4. Fallback al motor autónomo pericial local (100% sin API)
    bici = completar_con_catalogo(bici, aplicar_heuristica_peso=True)
    if peso_empirico_previo is None and bici.peso_kg is not None:
        bici._peso_estimado = True
    nota_auto, desglose_auto = valorar_autonomo(bici)
    log.info(f"[Perito Autónomo] {bici.titulo} -> {nota_auto}/10 (km={bici.km}, peso={bici.peso_kg} kg)")
    return bici, nota_auto, desglose_auto
