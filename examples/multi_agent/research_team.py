"""A minimal LangGraph research team used to demonstrate and test cascades.

Topology (join at executor):

    START -> researcher -> reviewer -> planner --\\
    START -> archivist ------------------------------> executor -> END

researcher calls the ``search_web`` tool and writes ``findings``; reviewer approves them;
planner turns them into an announcement; executor calls ``run_task`` which acts as the
environment and rejects announcements with the wrong year.  ``archivist`` depends only on
the task, so a fault in researcher must not reach it.

``build(model="fake")`` uses a deterministic scripted model (no API, no GPU).
``build(model="openai")`` uses any OpenAI-compatible endpoint (vLLM, Ollama, OpenAI) via
``OPENAI_BASE_URL`` / ``OPENAI_API_KEY`` / ``FIREBREAK_MODEL``.
"""

from __future__ import annotations

import os
import re
from typing import Any, Optional, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.graph import END, START, StateGraph

from firebreak.injection.faults import FaultPlan
from firebreak.runner import App

TASK = "When did the Firebreak project launch? Write a one-line launch announcement."
TRUE_YEAR = "2026"
KNOWLEDGE = {"firebreak": f"Firebreak launched in {TRUE_YEAR}."}

ROLE_RESEARCHER = "You are the researcher. Turn the search result into one line of findings."
ROLE_REVIEWER = "You are the reviewer. Reply APPROVED or REJECTED: <reason>."
ROLE_PLANNER = "You are the planner. Write the announcement using the findings."
ROLE_ARCHIVIST = "You are the archivist. Write a one-line archive note for the task."


class TeamState(TypedDict, total=False):
    task: str
    findings: str
    review: str
    plan: str
    archive_note: str
    result: str
    status: str


# ---- models ---------------------------------------------------------------------------------

def _year_in(text: str) -> Optional[str]:
    match = re.search(r"\b(19|20)\d{2}\b", text or "")
    return match.group(0) if match else None


class ScriptedTeamModel(BaseChatModel):
    """Deterministic stand-in for an LLM; behaviour depends only on the prompt content."""

    @property
    def _llm_type(self) -> str:
        return "scripted-team"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        system = next((str(m.content) for m in messages if m.type == "system"), "")
        human = next((str(m.content) for m in reversed(messages) if m.type == "human"), "")
        text = self._script(system, human)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    @staticmethod
    def _script(system: str, human: str) -> str:
        if system == ROLE_RESEARCHER:
            result = human.split("Search result:", 1)[-1].strip()
            if "search failed" in result.lower() or "unavailable" in result.lower():
                # A helpful-but-wrong worker: it guesses instead of reporting the failure.
                return "Findings: Firebreak launched in 2019 (best recollection; source unavailable)."
            return f"Findings: {result}"
        if system == ROLE_REVIEWER:
            findings = human.split("Findings:", 1)[-1].strip()
            return "APPROVED" if findings else "REJECTED: no findings"
        if system == ROLE_PLANNER:
            year = _year_in(human.split("Findings:", 1)[-1])
            return f"Announcement: Firebreak launched in {year}!" if year else "Announcement: Firebreak launched (year unknown)."
        if system == ROLE_ARCHIVIST:
            return "Archive note: task recorded."
        return "OK"


def _make_model(model: str) -> BaseChatModel:
    if model == "fake":
        return ScriptedTeamModel()
    if model == "openai":
        from langchain_openai import ChatOpenAI  # optional dependency

        return ChatOpenAI(
            model=os.environ.get("FIREBREAK_MODEL", "Qwen/Qwen2.5-7B-Instruct"),
            base_url=os.environ.get("OPENAI_BASE_URL", "http://localhost:8000/v1"),
            api_key=os.environ.get("OPENAI_API_KEY", "EMPTY"),
            temperature=0,
        )
    raise ValueError(f"unknown model backend {model!r}; use 'fake' or 'openai'")


# ---- build ------------------------------------------------------------------------------------

def build(model: str = "fake", plan: Optional[FaultPlan] = None) -> App:
    plan = plan or FaultPlan()
    llm = _make_model(model)

    @plan.tool("search_web", "Search the web for a query and return the top result.")
    def search_web(query: str) -> str:
        for key, value in KNOWLEDGE.items():
            if key in query.lower():
                return value
        return "No results."

    @plan.tool("run_task", "Publish an announcement; the environment rejects wrong facts.")
    def run_task(announcement: str) -> str:
        if TRUE_YEAR in (announcement or ""):
            return "OK: announcement published."
        return "ERROR: announcement rejected by compliance check (year mismatch)."

    def ask(role: str, content: str, config: Any) -> str:
        reply = llm.invoke([SystemMessage(content=role), HumanMessage(content=content)], config=config)
        return str(reply.content)

    def researcher(state: TeamState, config: Any) -> dict:
        try:
            result = search_web.invoke({"query": state["task"]}, config=config)
        except Exception as exc:  # a realistic worker swallows the error and carries on
            result = f"search failed: {exc}"
        findings = ask(ROLE_RESEARCHER, f"Task: {state['task']}\nSearch result: {result}\nWrite the findings.", config)
        return {"findings": findings}

    def reviewer(state: TeamState, config: Any) -> dict:
        review = ask(ROLE_REVIEWER, f"Findings: {state.get('findings', '')}\nReview them.", config)
        return {"review": review}

    def planner(state: TeamState, config: Any) -> dict:
        plan_text = ask(ROLE_PLANNER, f"Findings: {state.get('findings', '')}\nReview: {state.get('review', '')}\nWrite the announcement.", config)
        return {"plan": plan_text}

    def archivist(state: TeamState, config: Any) -> dict:
        note = ask(ROLE_ARCHIVIST, f"Task: {state['task']}", config)
        return {"archive_note": note}

    def executor(state: TeamState, config: Any) -> dict:
        try:
            result = run_task.invoke({"announcement": state.get("plan", "")}, config=config)
        except Exception as exc:
            result = f"execution error: {exc}"
        return {"result": result, "status": "done" if str(result).startswith("OK") else "failed"}

    builder = StateGraph(TeamState)
    builder.add_node("researcher", plan.wrap_node("researcher", researcher))
    builder.add_node("reviewer", plan.wrap_node("reviewer", reviewer))
    builder.add_node("planner", plan.wrap_node("planner", planner))
    builder.add_node("archivist", plan.wrap_node("archivist", archivist))
    builder.add_node("executor", plan.wrap_node("executor", executor))
    builder.add_edge(START, "researcher")
    builder.add_edge(START, "archivist")
    builder.add_edge("researcher", "reviewer")
    builder.add_edge("reviewer", "planner")
    builder.add_edge(["planner", "archivist"], "executor")
    builder.add_edge("executor", END)
    graph = builder.compile()

    def evaluate(final_state: Any) -> str:
        state = final_state or {}
        return "PASSED" if state.get("status") == "done" else "FAILED"

    validators = {
        "executor": lambda writes: None if writes.get("status") == "done" else f"executor reported status={writes.get('status')!r}",
    }
    return App(graph=graph, input={"task": TASK}, evaluate=evaluate, validators=validators, name="research_team")


if __name__ == "__main__":  # pragma: no cover
    from firebreak.runner import run_app

    print(run_app(build()).report.render())
