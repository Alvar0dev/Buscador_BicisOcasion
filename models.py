"""
models.py
Modelo de datos de una bicicleta encontrada.
"""

from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class Bicicleta:
    sitio: str               # Nombre del sitio (ej. "Bike Ocasión")
    bici_id: str             # ID único de la bici en el sitio (para dedup)
    titulo: str              # Título / nombre comercial
    precio: float            # Precio en euros
    url: str                 # Enlace directo de compra
    talla: Optional[str] = None
    modalidad: Optional[str] = None
    peso_kg: Optional[float] = None
    bateria_wh: Optional[int] = None
    range_extender_wh: Optional[int] = None
    cuadro_material: Optional[str] = None
    motor: Optional[str] = None
    km: Optional[int] = None
    ano: Optional[int] = None
    componentes: Optional[str] = None
    suspension_trasera: Optional[str] = None  # Amortiguador trasero -> doble suspensión
    garantia_anos: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)

    def resumen_corto(self) -> str:
        return f"{self.titulo} — {self.precio} € — {self.sitio}"
