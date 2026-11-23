"""ServiceNow tickets for approved requirement drafts: a local fake (default) or the Table API (`SN_BACKEND=rest`)."""
from copilot import config
from copilot.integrations.servicenow.fake import FakeServiceNow
from copilot.integrations.servicenow.models import TicketSystem, TicketSystemError
from copilot.integrations.servicenow.rest import RestServiceNow

__all__ = ["FakeServiceNow", "RestServiceNow", "TicketSystem", "TicketSystemError", "ticket_system"]


def ticket_system() -> TicketSystem:
    if config.SN_BACKEND == "rest":
        return RestServiceNow()
    return FakeServiceNow()
