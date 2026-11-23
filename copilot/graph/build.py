"""Graph wiring.

    START → route ─┬─► clarify / out_of_scope → END
                   └─► extract_date ─┬─► question: retrieve → answer_grounded → END
                                     ├─► validate: validate_invoice → retrieve_rule_docs → explain_findings → END
                                     ├─► compare:  compare_countries → END
                                     └─► draft_requirement: retrieve → draft_requirement → END
                   └─► create_ticket: approval (interrupt: a person approves, edits or rejects)
                                        ├─ approved → create_ticket → END
                                        └─ rejected → END ("not created")

The only edge into `create_ticket` comes from an approved `approval`; the node checks the approval again.
"""
from langgraph.graph import END, START, StateGraph

from copilot.graph.nodes.answer import answer_grounded, retrieve
from copilot.graph.nodes.compare import compare_countries
from copilot.graph.nodes.dates import extract_date
from copilot.graph.nodes.requirement import after_approval, approval, create_ticket, draft_requirement
from copilot.graph.nodes.route import clarify, out_of_scope, route
from copilot.graph.nodes.validate import explain_findings, retrieve_rule_docs, route_after_validation, validate_invoice
from copilot.graph.state import CopilotState


def after_route(state) -> str:
    if state["intent"] == "create_ticket":
        return "approval"
    return state["intent"] if state["intent"] in ("clarify", "out_of_scope") else "extract_date"


def after_dates(state) -> str:
    return "question" if state["intent"] == "draft_requirement" else state["intent"]


def after_retrieve(state) -> str:
    return "draft_requirement" if state["intent"] == "draft_requirement" else "answer_grounded"


def build_graph(checkpointer=None):
    graph = StateGraph(CopilotState)
    for name, node in [("route", route), ("clarify", clarify), ("out_of_scope", out_of_scope),
                       ("extract_date", extract_date), ("retrieve", retrieve), ("answer_grounded", answer_grounded),
                       ("validate_invoice", validate_invoice), ("retrieve_rule_docs", retrieve_rule_docs),
                       ("explain_findings", explain_findings), ("compare_countries", compare_countries),
                       ("draft_requirement", draft_requirement), ("approval", approval),
                       ("create_ticket", create_ticket)]:
        graph.add_node(name, node)
    graph.add_edge(START, "route")
    graph.add_conditional_edges("route", after_route, {"clarify": "clarify", "out_of_scope": "out_of_scope",
                                                       "extract_date": "extract_date", "approval": "approval"})
    graph.add_conditional_edges("extract_date", after_dates, {"question": "retrieve", "validate": "validate_invoice",
                                                              "compare": "compare_countries"})
    graph.add_conditional_edges("retrieve", after_retrieve, {"answer_grounded": "answer_grounded",
                                                             "draft_requirement": "draft_requirement"})
    graph.add_conditional_edges("approval", after_approval, {"create_ticket": "create_ticket", "end": END})
    graph.add_conditional_edges("validate_invoice", route_after_validation,
                                {"retrieve_rule_docs": "retrieve_rule_docs", "end": END})
    graph.add_edge("retrieve_rule_docs", "explain_findings")
    for last in ("clarify", "out_of_scope", "answer_grounded", "explain_findings", "compare_countries",
                 "draft_requirement", "create_ticket"):
        graph.add_edge(last, END)
    return graph.compile(checkpointer=checkpointer)
