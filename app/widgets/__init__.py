"""Dashboard widgets. Each module defines one widget and calls register(); importing it
here makes it available. The import order is also the order in which new default
widgets are placed on existing dashboards.

To add a widget: create app/widgets/<name>.py with a WidgetDefinition (and an APIRouter
if it needs its own routes, included in app/main.py), import it below, and add its
frontend component in frontend/src/widgets/<name>/ + frontend/src/widgets/index.ts.
"""
from app.widgets.registry import REGISTRY, WidgetContext, WidgetDefinition  # noqa: F401
from app.widgets import (  # noqa: F401
    email_summary,
    weather,
    nutrition,
    notes,
    news,
    journal,
    google_calendar,
    animal,
    gym,
    language,
    budget,
    assistant,
)
