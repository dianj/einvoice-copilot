"""Graph wiring.

    START → route ─┬─► clarify / out_of_scope → END
                   └─► extract_date ─┬─► question: retrieve → answer_grounded → END
                                     ├─► validate: validate_invoice → retrieve_rule_docs → explain_findings → END
                                     └─► compare:  compare_countries → END

Requirements drafting and ServiceNow tickets (with a human-approval interrupt) are added in E4.
"""
from langgraph.graph import END, START, StateGraph

from copilot.graph.nodes.answer import answer_grounded, retrieve
from copilot.graph.nodes.compare import compare_countries
from copilot.graph.nodes.dates import extract_date
from copilot.graph.nodes.route import clarify, out_of_scope, route
from copilot.graph.nodes.validate import explain_findings, retrieve_rule_docs, route_after_validation, validate_invoice
from copilot.graph.state import CopilotState


def after_route(state) -> str:
    return state["intent"] if state["intent"] in ("clarify", "out_of_scope") else "extract_date"


def after_dates(state) -> str:
    return state["intent"]


def build_graph(checkpointer=None):
    graph = StateGraph(CopilotState)
    for name, node in [("route", route), ("clarify", clarify), ("out_of_scope", out_of_scope),
                       ("extract_date", extract_date), ("retrieve", retrieve), ("answer_grounded", answer_grounded),
                       ("validate_invoice", validate_invoice), ("retrieve_rule_docs", retrieve_rule_docs),
                       ("explain_findings", explain_findings), ("compare_countries", compare_countries)]:
        graph.add_node(name, node)
    graph.add_edge(START, "route")
    graph.add_conditional_edges("route", after_route, {"clarify": "clarify", "out_of_scope": "out_of_scope",
                                                       "extract_date": "extract_date"})
    graph.add_conditional_edges("extract_date", after_dates, {"question": "retrieve", "validate": "validate_invoice",
                                                              "compare": "compare_countries"})
    graph.add_edge("retrieve", "answer_grounded")
    graph.add_conditional_edges("validate_invoice", route_after_validation,
                                {"retrieve_rule_docs": "retrieve_rule_docs", "end": END})
    graph.add_edge("retrieve_rule_docs", "explain_findings")
    for last in ("clarify", "out_of_scope", "answer_grounded", "explain_findings", "compare_countries"):
        graph.add_edge(last, END)
    return graph.compile(checkpointer=checkpointer)
