# The widget registry: every dashboard widget describes itself here once, and the
# generic /widgets routes + the frontend grid work off these definitions.
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Literal, Optional

from sqlalchemy.orm import Session

from app.models import User


@dataclass(frozen=True)
class ConfigField:
    """One user-editable setting, rendered as a form field by the frontend."""
    key: str
    label: str
    type: Literal["number", "boolean", "select", "text"]
    default: Any
    min: Optional[float] = None
    max: Optional[float] = None
    options: Optional[list[str]] = None  # for type="select"

    def validate(self, value: Any) -> Any:
        if self.type == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{self.label} must be a number")
            if self.min is not None and value < self.min:
                raise ValueError(f"{self.label} must be at least {self.min:g}")
            if self.max is not None and value > self.max:
                raise ValueError(f"{self.label} must be at most {self.max:g}")
            return int(value) if float(value).is_integer() else value
        if self.type == "boolean":
            if not isinstance(value, bool):
                raise ValueError(f"{self.label} must be true or false")
            return value
        if self.type == "select":
            if value not in (self.options or []):
                raise ValueError(f"{self.label} must be one of {self.options}")
            return value
        if not isinstance(value, str) or len(value) > 500:
            raise ValueError(f"{self.label} must be text (max 500 characters)")
        return value


@dataclass(frozen=True)
class WidgetContext:
    """Viewer context the frontend sends with every data request."""
    since: datetime  # viewer's local midnight, as naive UTC (how the DB stores times)
    tz: Optional[str]  # IANA timezone name, e.g. "Europe/Copenhagen"


# (db, user, settings, ctx) -> widget-specific JSON-able data
FetchFn = Callable[[Session, User, dict, WidgetContext], dict]


@dataclass(frozen=True)
class WidgetDefinition:
    id: str
    name: str
    description: str
    fetch: FetchFn
    default_size: tuple[int, int] = (6, 8)  # grid units (w, h) on a 12-column grid
    min_size: tuple[int, int] = (3, 4)
    refresh_seconds: int = 300  # how often the frontend re-fetches while open
    enabled_by_default: bool = False  # added to a new user's dashboard automatically
    config_fields: tuple[ConfigField, ...] = field(default_factory=tuple)

    def default_settings(self) -> dict:
        return {f.key: f.default for f in self.config_fields}

    def manifest(self) -> dict:
        """What the frontend needs to know about this widget (no functions)."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "default_size": {"w": self.default_size[0], "h": self.default_size[1]},
            "min_size": {"w": self.min_size[0], "h": self.min_size[1]},
            "refresh_seconds": self.refresh_seconds,
            "config_fields": [
                {k: v for k, v in f.__dict__.items() if v is not None} for f in self.config_fields
            ],
        }


REGISTRY: dict[str, WidgetDefinition] = {}


def register(definition: WidgetDefinition) -> WidgetDefinition:
    if definition.id in REGISTRY:
        raise ValueError(f"Widget {definition.id!r} is registered twice")
    REGISTRY[definition.id] = definition
    return definition
