# Importing a widget module registers it. To add a widget: create app/widgets/<name>.py
# that calls register(WidgetDefinition(...)), import it here, and add its frontend
# component in frontend/src/widgets/index.ts.
from app.widgets.registry import REGISTRY, WidgetContext, WidgetDefinition  # noqa: F401
from app.widgets import email_summary, weather, nutrition, notes, news, journal, google_calendar, animal  # noqa: F401  (order = placement order for new widgets)
