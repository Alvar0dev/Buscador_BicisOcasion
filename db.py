"""
db.py
Base de datos ligera SQLite para registrar bicicletas ya enviadas por Telegram
y mantener el historial de precios y tiempo en stock de todo el catálogo pre-filtrado.
Garantiza que no lleguen alertas duplicadas en días consecutivos, salvo que bajen de precio (S12).
"""

import sqlite3
from datetime import datetime, date
from typing import Optional, Tuple, Dict, Any, List
import config as cfg
from models import Bicicleta


class BaseDatos:
    def __init__(self, ruta: Optional[str] = None) -> None:
        self.ruta = ruta if ruta is not None else cfg.DB_PATH
        self._crear_tabla()

    def _conectar(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.ruta)
        conn.row_factory = sqlite3.Row
        return conn

    def _crear_tabla(self) -> None:
        with self._conectar() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bicis_enviadas (
                    bici_id      TEXT PRIMARY KEY,
                    sitio        TEXT NOT NULL,
                    titulo       TEXT NOT NULL,
                    precio       REAL NOT NULL,
                    url          TEXT NOT NULL,
                    nota         REAL NOT NULL,
                    fecha_envio  TEXT NOT NULL DEFAULT (datetime('now')),
                    precio_anterior REAL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS historial_catalogo (
                    bici_id             TEXT PRIMARY KEY,
                    sitio               TEXT NOT NULL,
                    titulo              TEXT NOT NULL,
                    url                 TEXT NOT NULL,
                    precio_actual       REAL NOT NULL,
                    precio_inicial      REAL NOT NULL,
                    precio_minimo       REAL NOT NULL,
                    fecha_primera_vez   TEXT NOT NULL DEFAULT (date('now')),
                    fecha_ultima_vez    TEXT NOT NULL DEFAULT (date('now')),
                    dias_en_stock       INTEGER NOT NULL DEFAULT 0,
                    rebajas_detectadas  INTEGER NOT NULL DEFAULT 0,
                    pvp_original        REAL
                )
                """
            )
            # Migración: asegurar que la columna pvp_original exista en bases de datos previas
            try:
                conn.execute("ALTER TABLE historial_catalogo ADD COLUMN pvp_original REAL")
            except Exception:
                pass
            conn.commit()

    def ya_enviada(self, bici_id: str) -> bool:
        """Devuelve True si la bici ya fue notificada anteriormente."""
        with self._conectar() as conn:
            fila = conn.execute(
                "SELECT 1 FROM bicis_enviadas WHERE bici_id = ?", (bici_id,)
            ).fetchone()
        return fila is not None

    def precio_previo(self, bici_id: str) -> Optional[float]:
        """Devuelve el último precio registrado para detectar bajadas (S12)."""
        with self._conectar() as conn:
            fila = conn.execute(
                "SELECT precio FROM bicis_enviadas WHERE bici_id = ?", (bici_id,)
            ).fetchone()
        return fila["precio"] if fila else None

    def registrar(self, bici: Bicicleta, nota: float, precio_anterior: Optional[float] = None) -> None:
        """Guarda la bicicleta como enviada (S12)."""
        with self._conectar() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO bicis_enviadas
                    (bici_id, sitio, titulo, precio, url, nota, precio_anterior)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bici.bici_id,
                    bici.sitio,
                    bici.titulo,
                    bici.precio,
                    bici.url,
                    nota,
                    precio_anterior,
                ),
            )
            conn.commit()

    def debe_reenviarse(self, bici: Bicicleta, nota: float) -> bool:
        """
        Decide si se debe notificar esta bicicleta.
        - Si nunca se envió: True.
        - Si ya se envió y el precio bajó: True (re-alerta por bajada de precio).
        - Si ya se envió y el precio no bajó: False (evita duplicados, S12).
        """
        if not self.ya_enviada(bici.bici_id):
            return True
        previo = self.precio_previo(bici.bici_id)
        if previo is None:
            return False
        return bici.precio < previo

    # ---------------------------------------------------------------------------
    # HISTORIAL DE CATÁLOGO Y TIEMPO EN STOCK (TODO 1)
    # ---------------------------------------------------------------------------

    def registrar_en_catalogo(self, bici: Bicicleta) -> Dict[str, Any]:
        """
        Registra o actualiza el seguimiento diario de la bicicleta en el catálogo.
        Calcula días en stock, rebajas detectadas y ahorro acumulado.
        """
        hoy_str = date.today().strftime("%Y-%m-%d")
        pvp_orig = getattr(bici, "pvp_original", None)
        with self._conectar() as conn:
            fila = conn.execute(
                "SELECT * FROM historial_catalogo WHERE bici_id = ?", (bici.bici_id,)
            ).fetchone()

            if fila is None:
                # Primera vez que se detecta esta bicicleta
                conn.execute(
                    """
                    INSERT INTO historial_catalogo
                        (bici_id, sitio, titulo, url, precio_actual, precio_inicial,
                         precio_minimo, fecha_primera_vez, fecha_ultima_vez,
                         dias_en_stock, rebajas_detectadas, pvp_original)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
                    """,
                    (
                        bici.bici_id,
                        bici.sitio,
                        bici.titulo,
                        bici.url,
                        bici.precio,
                        bici.precio,
                        bici.precio,
                        hoy_str,
                        hoy_str,
                        pvp_orig,
                    ),
                )
                conn.commit()
                return {
                    "dias_en_stock": 0,
                    "rebajas_detectadas": 0,
                    "precio_inicial": bici.precio,
                    "precio_minimo": bici.precio,
                    "precio_actual": bici.precio,
                    "pvp_original": pvp_orig,
                    "ahorro_eur": 0.0,
                    "entrada_desde_vigilancia": False,
                }
            else:
                precio_inicial = float(fila["precio_inicial"])
                precio_actual_prev = float(fila["precio_actual"])
                precio_minimo = min(float(fila["precio_minimo"]), bici.precio)
                rebajas = int(fila["rebajas_detectadas"])
                if bici.precio < precio_actual_prev:
                    rebajas += 1

                fecha_primera = fila["fecha_primera_vez"]
                try:
                    f_primera = datetime.strptime(fecha_primera, "%Y-%m-%d").date()
                    dias_stock = max(0, (date.today() - f_primera).days)
                except Exception:
                    dias_stock = int(fila["dias_en_stock"])

                pvp_guardado = fila["pvp_original"] if "pvp_original" in fila.keys() else None
                if pvp_orig is not None:
                    pvp_guardado = pvp_orig

                conn.execute(
                    """
                    UPDATE historial_catalogo
                    SET precio_actual = ?,
                        precio_minimo = ?,
                        fecha_ultima_vez = ?,
                        dias_en_stock = ?,
                        rebajas_detectadas = ?,
                        pvp_original = ?
                    WHERE bici_id = ?
                    """,
                    (
                        bici.precio,
                        precio_minimo,
                        hoy_str,
                        dias_stock,
                        rebajas,
                        pvp_guardado,
                        bici.bici_id,
                    ),
                )
                conn.commit()
                ahorro = max(0.0, precio_inicial - bici.precio)
                entrada_vigilancia = bool(
                    rebajas > 0
                    and (
                        (precio_inicial > cfg.PRECIO_MAX_EUR and bici.precio <= cfg.PRECIO_MAX_EUR)
                        or (precio_inicial > cfg.PRECIO_MAX_EXCEPCIONAL_EUR and bici.precio <= cfg.PRECIO_MAX_EXCEPCIONAL_EUR)
                        or ahorro >= 200.0
                    )
                )
                return {
                    "dias_en_stock": dias_stock,
                    "rebajas_detectadas": rebajas,
                    "precio_inicial": precio_inicial,
                    "precio_minimo": precio_minimo,
                    "precio_actual": bici.precio,
                    "ahorro_eur": ahorro,
                    "entrada_desde_vigilancia": entrada_vigilancia,
                }

    def obtener_seguimiento(self, bici_id: str) -> Optional[Dict[str, Any]]:
        """Devuelve métricas de seguimiento de una bicicleta registrada."""
        with self._conectar() as conn:
            fila = conn.execute(
                "SELECT * FROM historial_catalogo WHERE bici_id = ?", (bici_id,)
            ).fetchone()
            if not fila:
                return None
            precio_inicial = float(fila["precio_inicial"])
            precio_actual = float(fila["precio_actual"])
            rebajas = int(fila["rebajas_detectadas"])
            ahorro = max(0.0, precio_inicial - precio_actual)
            entrada_vigilancia = bool(
                rebajas > 0
                and (
                    (precio_inicial > cfg.PRECIO_MAX_EUR and precio_actual <= cfg.PRECIO_MAX_EUR)
                    or (precio_inicial > cfg.PRECIO_MAX_EXCEPCIONAL_EUR and precio_actual <= cfg.PRECIO_MAX_EXCEPCIONAL_EUR)
                    or ahorro >= 200.0
                )
            )
            return {
                "dias_en_stock": int(fila["dias_en_stock"]),
                "rebajas_detectadas": rebajas,
                "precio_inicial": precio_inicial,
                "precio_minimo": float(fila["precio_minimo"]),
                "precio_actual": precio_actual,
                "ahorro_eur": ahorro,
                "entrada_desde_vigilancia": entrada_vigilancia,
                "fecha_primera_vez": fila["fecha_primera_vez"],
                "fecha_ultima_vez": fila["fecha_ultima_vez"],
            }

    def obtener_estadisticas_mercado(self) -> Dict[str, Any]:
        """
        Genera la radiografía del mercado a partir del historial de catálogo.
        Calcula permanencia en stock (días), cuotas, precios medios,
        ahorros acumulados por rebaja y descuentos respecto al PVP original.
        """
        with self._conectar() as conn:
            filas = conn.execute("SELECT * FROM historial_catalogo").fetchall()

        if not filas:
            return {
                "total": 0,
                "por_sitio": {},
                "metricas_por_sitio": {},
                "modelos_clave": {},
                "en_vigilancia": [],
                "con_rebajas": [],
                "resumen_global": {
                    "total": 0,
                    "dias_stock_medio": 0.0,
                    "precio_medio": 0.0,
                    "con_rebajas": 0,
                    "ahorro_total_acumulado": 0.0,
                    "ahorro_medio_rebajas": 0.0,
                    "en_vigilancia": 0,
                    "descuento_pvp_medio_pct": None,
                },
            }

        total = len(filas)
        por_sitio: Dict[str, int] = {}
        dias_por_sitio: Dict[str, List[int]] = {}
        precios_por_sitio: Dict[str, List[float]] = {}
        ahorros_por_sitio: Dict[str, List[float]] = {}
        pvp_pcts_por_sitio: Dict[str, List[float]] = {}

        todos_los_dias: List[int] = []
        todos_los_precios: List[float] = []
        todos_los_pvp_pcts: List[float] = []

        con_rebajas: List[Dict[str, Any]] = []
        en_vigilancia: List[Dict[str, Any]] = []

        familias_clave = {
            "Orbea Rise": ["orbea rise", "rise h", "rise m"],
            "BH iLynx": ["ilynx", "i-lynx"],
            "Specialized Levo SL": ["levo sl"],
            "Trek Fuel EXe": ["fuel exe"],
            "Scott Lumen": ["lumen"],
            "Mondraker Neat": ["neat"],
        }
        stats_familias: Dict[str, Dict[str, Any]] = {
            f: {
                "unidades": 0,
                "precios": [],
                "dias": [],
                "ahorros": [],
                "pvp_pcts": [],
                "precio_min": None,
                "precio_medio": None,
                "dias_stock_medio": 0.0,
                "ahorro_medio_rebajas": 0.0,
                "descuento_pvp_medio_pct": None,
            }
            for f in familias_clave
        }

        for f in filas:
            sitio = f["sitio"]
            por_sitio[sitio] = por_sitio.get(sitio, 0) + 1
            dias_s = int(f["dias_en_stock"])
            precio = float(f["precio_actual"])
            p_ini = float(f["precio_inicial"])
            titulo = f["titulo"].lower()

            pvp_orig = None
            if "pvp_original" in f.keys() and f["pvp_original"] is not None:
                try:
                    pvp_orig = float(f["pvp_original"])
                except (ValueError, TypeError):
                    pvp_orig = None

            dias_por_sitio.setdefault(sitio, []).append(dias_s)
            precios_por_sitio.setdefault(sitio, []).append(precio)
            todos_los_dias.append(dias_s)
            todos_los_precios.append(precio)

            ahorro_rebaja = 0.0
            if int(f["rebajas_detectadas"]) > 0:
                ahorro_rebaja = max(0.0, p_ini - precio)
                ahorros_por_sitio.setdefault(sitio, []).append(ahorro_rebaja)
                con_rebajas.append({
                    "titulo": f["titulo"],
                    "sitio": f["sitio"],
                    "precio_actual": precio,
                    "precio_inicial": p_ini,
                    "ahorro": ahorro_rebaja,
                    "dias": dias_s,
                    "entrada_vigilancia": bool(p_ini > cfg.PRECIO_MAX_EUR and precio <= cfg.PRECIO_MAX_EUR),
                    "url": f["url"],
                })

            pct_pvp = None
            if pvp_orig and pvp_orig > precio:
                pct_pvp = ((pvp_orig - precio) / pvp_orig) * 100.0
                pvp_pcts_por_sitio.setdefault(sitio, []).append(pct_pvp)
                todos_los_pvp_pcts.append(pct_pvp)

            if 2900.0 <= precio <= 3500.0:
                en_vigilancia.append({
                    "titulo": f["titulo"],
                    "sitio": f["sitio"],
                    "precio": precio,
                    "dias": dias_s,
                    "url": f["url"],
                })

            for nom_fam, tokens in familias_clave.items():
                if any(t in titulo for t in tokens):
                    stats_familias[nom_fam]["unidades"] += 1
                    stats_familias[nom_fam]["precios"].append(precio)
                    stats_familias[nom_fam]["dias"].append(dias_s)
                    if ahorro_rebaja > 0:
                        stats_familias[nom_fam]["ahorros"].append(ahorro_rebaja)
                    if pct_pvp is not None:
                        stats_familias[nom_fam]["pvp_pcts"].append(pct_pvp)
                    break

        metricas_por_sitio: Dict[str, Dict[str, Any]] = {}
        for sitio, cant in por_sitio.items():
            dias_arr = dias_por_sitio.get(sitio, [])
            precios_arr = precios_por_sitio.get(sitio, [])
            ahorros_arr = ahorros_por_sitio.get(sitio, [])
            pvp_arr = pvp_pcts_por_sitio.get(sitio, [])

            dias_medio = round(sum(dias_arr) / len(dias_arr), 1) if dias_arr else 0.0
            p_medio = round(sum(precios_arr) / len(precios_arr), 2) if precios_arr else 0.0
            ahorro_medio = round(sum(ahorros_arr) / len(ahorros_arr), 2) if ahorros_arr else 0.0
            dto_pvp_medio = round(sum(pvp_arr) / len(pvp_arr), 1) if pvp_arr else None

            metricas_por_sitio[sitio] = {
                "unidades": cant,
                "cuota_pct": round((cant / total * 100.0), 1) if total > 0 else 0.0,
                "dias_stock_medio": dias_medio,
                "precio_medio": p_medio,
                "con_rebajas": len(ahorros_arr),
                "ahorro_medio_rebajas": ahorro_medio,
                "descuento_pvp_medio_pct": dto_pvp_medio,
            }

        for nom_fam, data in stats_familias.items():
            precios = data.pop("precios")
            dias = data.pop("dias")
            ahorros = data.pop("ahorros")
            pvp_pcts = data.pop("pvp_pcts")
            if precios:
                data["precio_min"] = round(min(precios), 2)
                data["precio_medio"] = round(sum(precios) / len(precios), 2)
                data["dias_stock_medio"] = round(sum(dias) / len(dias), 1) if dias else 0.0
                data["ahorro_medio_rebajas"] = round(sum(ahorros) / len(ahorros), 2) if ahorros else 0.0
                data["descuento_pvp_medio_pct"] = round(sum(pvp_pcts) / len(pvp_pcts), 1) if pvp_pcts else None

        con_rebajas.sort(key=lambda x: x["ahorro"], reverse=True)
        en_vigilancia.sort(key=lambda x: x["precio"])

        resumen_global = {
            "total": total,
            "dias_stock_medio": round(sum(todos_los_dias) / total, 1) if total > 0 else 0.0,
            "precio_medio": round(sum(todos_los_precios) / total, 2) if total > 0 else 0.0,
            "con_rebajas": len(con_rebajas),
            "ahorro_total_acumulado": round(sum(r["ahorro"] for r in con_rebajas), 2),
            "ahorro_medio_rebajas": round(sum(r["ahorro"] for r in con_rebajas) / len(con_rebajas), 2) if con_rebajas else 0.0,
            "en_vigilancia": len(en_vigilancia),
            "descuento_pvp_medio_pct": round(sum(todos_los_pvp_pcts) / len(todos_los_pvp_pcts), 1) if todos_los_pvp_pcts else None,
        }

        return {
            "total": total,
            "por_sitio": por_sitio,
            "metricas_por_sitio": metricas_por_sitio,
            "modelos_clave": {k: v for k, v in stats_familias.items() if v["unidades"] > 0},
            "con_rebajas": con_rebajas,
            "en_vigilancia": en_vigilancia,
            "resumen_global": resumen_global,
        }
