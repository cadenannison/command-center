"""City search building blocks: what a candidate place is and what a query may look like (0180)."""

from pydantic import BaseModel, ConfigDict, Field

MIN_QUERY_LENGTH = 2
MAX_QUERY_LENGTH = 100
MAX_CANDIDATES = 5


class GeocodeCandidate(BaseModel):
    """One place a city search found. The user picks one; nothing here is ever chosen for them."""

    model_config = ConfigDict(frozen=True)

    name: str
    region: str | None = None
    country: str | None = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    population: int | None = Field(default=None, ge=0)


def normalise_query(text: str) -> str:
    """The query with surrounding whitespace removed and inner runs of whitespace made one space."""
    return " ".join(text.split())
