from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class PrediccionRequest(BaseModel):
    texto: str = Field(..., max_length=20000)
    html: Optional[str] = Field(default=None, max_length=200000)

    @field_validator("texto")
    @classmethod
    def texto_no_vacio(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("El texto no puede estar vacío")
        return v


class Rasgo(BaseModel):
    rasgo: str
    categoria: str
    valor: float
    activo: bool
    descripcion: str


class PrediccionResponse(BaseModel):
    es_spam: bool
    probabilidad: float
    rasgos_detectados: List[Rasgo]