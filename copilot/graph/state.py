"""The graph state, kept by the checkpointer per thread.

Values are plain JSON types (dates as ISO strings, reports and passages as dicts), so a checkpoint reads the same
after a restart and in any tool. `messages` accumulates across turns; the per-turn fields are reset by every new
message (see `copilot.graph.run.turn_input`). `requirement_draft` and `ticket` stay with the thread: "create the
ticket" refers to the draft of an earlier turn.
"""
import operator
from typing import Annotated, Literal, TypedDict

Intent = Literal["question", "validate", "compare", "draft_requirement", "create_ticket", "clarify", "out_of_scope"]


class CopilotState(TypedDict, total=False):
    messages: Annotated[list[dict], operator.add]   # {"role", "content"} for the whole thread
    # --- this turn's input
    user_input: str
    attachment_id: str | None
    params: dict                    # validation parameters chosen by the user (country, stage, ...)
    action: str | None              # a button press ("create_ticket"): decided by code, the model is not asked
    # --- set by the nodes
    language: Literal["en", "bg"]
    intent: Intent
    clarify: str                    # which clarifying question (code rule), when intent == "clarify"
    clarify_options: list[str]      # the likely intents to offer, when the route check was not sure
    countries: list[str]
    date_phrases: list[str]
    search_query: str
    dates: list[str]                # 1-3 ISO dates the answer is about
    date_source: Literal["question", "invoice", "today"]
    retrievals: list[dict]          # per date: {as_of, answerable, top_vector_score, passages}
    report: dict | None             # the rule engine's ValidationReport
    rule_passages: list[dict]
    explanations: list[dict]
    comparison: dict | None
    approval: dict | None           # this turn's decision at the approval interrupt: {approved, draft_hash}
    # --- kept for the thread
    requirement_draft: dict | None  # the last checked draft (RequirementDraft as JSON)
    ticket: dict | None             # the last ticket created from it (TicketRef as JSON)
    answer: str
    citations: list[str]
    notes: list[str]                # what the code decided or corrected, shown to the user
