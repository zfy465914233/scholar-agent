"""Domain agent control loop with explicit role boundaries.

This module formalizes the agent architecture around four roles:

  Router     — classifies the query and decides the execution path
  Researcher — gathers evidence (local retrieval + optional web search)
  Synthesizer — produces a structured answer from evidence
  Curator    — manages knowledge lifecycle (distill, promote, review)

The state machine drives the execution through these stages:

  ROUTE → RESEARCH → SYNTHESIZE → CURATE → DONE

Each state transition is explicit and testable. The agent can loop back
from SYNTHESIZE to RESEARCH if evidence is insufficient.

Usage:
  from agent import DomainAgent
  agent = DomainAgent()
  result = agent.run("what is a markov chain")
"""

from __future__ import annotations

import json
import logging
import sys
from enum import Enum
from pathlib import Path
from typing import Any

from scholar_agent.engine.exceptions import ScholarError, ResearchError, SynthesisError

ENGINE_DIR = Path(__file__).resolve().parent
DEFAULT_INDEX = Path(__file__).resolve().parents[2] / "indexes" / "local" / "index.json"

logger = logging.getLogger(__name__)


# ── State machine ──────────────────────────────────────────────────

class AgentState(str, Enum):
    ROUTE = "route"
    RESEARCH = "research"
    SYNTHESIZE = "synthesize"
    CURATE = "curate"
    DONE = "done"


# ── Router ─────────────────────────────────────────────────────────

class Router:
    """Classifies the query and determines the execution path.

    Route types:
      local-led   — local knowledge is sufficient (definitions, derivations)
      web-led     — freshness matters, web evidence is primary
      mixed       — blend local and web evidence
      context-led — direct context inspection needed (debugging, code)
    """

    def classify(self, query: str, index_path: Path = DEFAULT_INDEX) -> str:
        """Classify a query into a route type.

        Uses in-process classification from orchestrate_research module.
        Falls back to subprocess if import fails (e.g. when scripts/ not on sys.path).
        """
        try:
            from orchestrate_research import classify_route
            return classify_route(query, index_path)
        except ImportError:
            logger.debug("Falling back to subprocess for route classification")
            import subprocess
            result = subprocess.run(
                [sys.executable, str(ENGINE_DIR / "orchestrate_research.py"),
                 query, "--mode", "auto", "--index", str(index_path)],
                capture_output=True, text=True, cwd=ENGINE_DIR,
            )
            if result.returncode != 0:
                raise ResearchError(f"Router failed: {result.stderr}")
            return json.loads(result.stdout).get("route", "mixed")

    def should_research_web(self, route: str) -> bool:
        return route in {"web-led", "mixed"}

    def should_research_local(self, route: str) -> bool:
        return route in {"local-led", "mixed", "web-led"}


# ── Researcher ─────────────────────────────────────────────────────

class Researcher:
    """Gathers evidence from local and web sources.

    Builds an answer context with direct support, inference notes,
    uncertainty notes, and citations.
    """

    def __init__(
        self,
        index_path: Path = DEFAULT_INDEX,
        research_script: Path | None = None,
    ) -> None:
        self.index_path = index_path
        self.research_script = research_script or ENGINE_DIR / "research_harness.py"

    def gather(self, query: str, route: str) -> dict[str, Any]:
        """Gather evidence and build answer context.

        Uses in-process calls when possible, subprocess fallback otherwise.
        """
        try:
            from orchestrate_research import classify_route, build_decision, generate_web_evidence
            from build_evidence_pack import build_evidence_pack
            from build_answer_context import build_answer_context
            import tempfile

            warnings: list[str] = []
            generated_web_path: Path | None = None

            if route in {"web-led", "mixed"}:
                generated_web_path, warning = generate_web_evidence(query, self.research_script)
                if warning:
                    warnings.append(warning)

            include_web = generated_web_path
            evidence_pack = build_evidence_pack(query, self.index_path, include_web, 5)
            _ = build_decision(route, has_web_evidence=include_web is not None)
            payload = build_answer_context(query, route, evidence_pack, warnings)

            if generated_web_path is not None:
                generated_web_path.unlink(missing_ok=True)

            return payload
        except ImportError:
            logger.debug("Falling back to subprocess for research")
            import subprocess
            args = [
                query, "--mode", route,
                "--index", str(self.index_path),
                "--research-script", str(self.research_script),
            ]
            result = subprocess.run(
                [sys.executable, str(ENGINE_DIR / "build_answer_context.py")] + args,
                capture_output=True, text=True, cwd=ENGINE_DIR,
            )
            if result.returncode != 0:
                raise ResearchError(f"Researcher failed: {result.stderr}")
            return json.loads(result.stdout)

    def is_evidence_sufficient(self, answer_context: dict[str, Any]) -> tuple[bool, str]:
        """Check if the gathered evidence is sufficient for synthesis.

        Returns (is_sufficient, reason).
        """
        direct = answer_context.get("direct_support", [])
        uncertainty = answer_context.get("uncertainty_notes", [])

        if not direct:
            return False, "No direct evidence found."

        if len(direct) == 0 and any("no direct evidence" in n.lower() for n in uncertainty):
            return False, "Evidence is too weak for confident synthesis."

        return True, ""


# ── Synthesizer ────────────────────────────────────────────────────

class Synthesizer:
    """Produces a structured answer from evidence using an LLM."""

    def __init__(self, model: str | None = None) -> None:
        self.model = model

    def render_prompt(self, answer_context: dict[str, Any]) -> dict[str, Any]:
        """Render answer context into a model-facing prompt bundle.

        Uses in-process call when possible, subprocess fallback otherwise.
        """
        try:
            from render_answer_bundle import render_user_prompt, SYSTEM_PROMPT
            user_prompt = render_user_prompt(answer_context)
            return {
                "system_prompt": SYSTEM_PROMPT,
                "user_prompt": user_prompt,
                "metadata": {
                    "query": answer_context.get("query", ""),
                    "route": answer_context.get("route", ""),
                },
                "citations": answer_context.get("citations", []),
            }
        except ImportError:
            logger.debug("Falling back to subprocess for prompt rendering")
            import subprocess
            ctx_json = json.dumps(answer_context, ensure_ascii=False)
            result = subprocess.run(
                [sys.executable, str(ENGINE_DIR / "render_answer_bundle.py"), "--answer-context-json", "-"],
                input=ctx_json, capture_output=True, text=True, cwd=ENGINE_DIR,
            )
            if result.returncode != 0:
                raise SynthesisError(f"Synthesizer render failed: {result.stderr}")
            return json.loads(result.stdout)

    def synthesize(self, prompt_bundle: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
        """Call the LLM to generate a structured answer.

        Uses in-process call when possible, subprocess fallback otherwise.
        """
        try:
            from synthesize_answer import synthesize as _synthesize
            return _synthesize(prompt_bundle, self.model or "gpt-4o-mini", dry_run=dry_run)
        except ImportError:
            logger.debug("Falling back to subprocess for synthesis")
            import subprocess
            args = ["--prompt-bundle", "-"]
            if self.model:
                args.extend(["--model", self.model])
            if dry_run:
                args.append("--dry-run")
            result = subprocess.run(
                [sys.executable, str(ENGINE_DIR / "synthesize_answer.py")] + args,
                input=json.dumps(prompt_bundle, ensure_ascii=False),
                capture_output=True, text=True, cwd=ENGINE_DIR,
            )
            if result.returncode != 0:
                raise SynthesisError(f"Synthesizer failed: {result.stderr}")
            return json.loads(result.stdout)


# ── Curator ────────────────────────────────────────────────────────

class Curator:
    """Manages knowledge lifecycle: distill answers, promote knowledge.

    This is a thin wrapper for now. Full lifecycle management (stale
    detection, dedup, conflict resolution) will come in Phase 5.
    """

    def distill(self, answer_output: dict[str, Any]) -> dict[str, Any] | None:
        """Distill an answer into a draft knowledge card."""
        answer_context = answer_output.get("intermediate", {}).get("answer_context")
        if not answer_context:
            return None

        try:
            from distill_knowledge import build_markdown
            markdown = build_markdown(answer_context)
            return {"markdown": markdown, "status": "draft"}
        except ImportError:
            logger.warning("distill_knowledge module not importable, skipping distillation")
            return None

    def promote(self, draft_path: Path, knowledge_root: Path) -> bool:
        """Promote a draft card into the knowledge tree."""
        import subprocess
        result = subprocess.run(
            [
                sys.executable, str(ENGINE_DIR / "promote_draft.py"),
                str(draft_path),
                "--knowledge-root", str(knowledge_root),
            ],
            capture_output=True, text=True, cwd=ENGINE_DIR,
        )
        return result.returncode == 0


# ── Query refinement ──────────────────────────────────────────────────

def refine_query(
    original_query: str,
    reason: str,
    answer_context: dict[str, Any],
) -> str:
    """Generate a refined query when evidence is insufficient.

    Uses uncertainty notes to identify gaps and constructs a broader query.
    """
    uncertainty = answer_context.get("uncertainty_notes", [])
    direct = answer_context.get("direct_support", [])

    # Extract key terms from existing evidence titles
    evidence_terms: set[str] = set()
    for item in direct:
        title = str(item.get("support", "") or item.get("title", ""))
        for word in title.split():
            if len(word) > 4:
                evidence_terms.add(word.lower())

    # Build refined query by appending context from uncertainty
    parts = [original_query]
    for note in uncertainty[:2]:
        clean = note.rstrip(".")
        if clean and clean not in parts:
            parts.append(clean)

    # Add evidence terms to widen the search
    if evidence_terms:
        extra = " ".join(sorted(evidence_terms)[:3])
        parts.append(extra)

    refined = " ".join(parts)
    if len(refined) > 200:
        refined = refined[:200]
    return refined


# ── Agent ──────────────────────────────────────────────────────────

class DomainAgent:
    """Domain-aware agent that orchestrates the full research-answer cycle.

    State machine:
      ROUTE → RESEARCH → SYNTHESIZE → (optional CURATE) → DONE

    If evidence is insufficient after RESEARCH, the agent can loop back
    with a refined query (max retries configurable).
    """

    def __init__(
        self,
        index_path: Path = DEFAULT_INDEX,
        research_script: Path | None = None,
        model: str | None = None,
        max_retries: int = 1,
    ) -> None:
        self.router = Router()
        self.researcher = Researcher(index_path, research_script)
        self.synthesizer = Synthesizer(model)
        self.curator = Curator()
        self.max_retries = max_retries
        self.index_path = index_path

    def run(
        self,
        query: str,
        dry_run: bool = False,
        curate: bool = False,
    ) -> dict[str, Any]:
        """Execute the full agent cycle and return the result."""
        state = AgentState.ROUTE
        route: str = ""
        answer_context: dict[str, Any] = {}
        prompt_bundle: dict[str, Any] = {}
        answer: dict[str, Any] = {}
        transitions: list[dict[str, str]] = []
        retries = 0

        while state != AgentState.DONE:
            transitions.append({"from": state.value, "to": ""})

            if state == AgentState.ROUTE:
                route = self.router.classify(query, self.index_path)
                state = AgentState.RESEARCH
                transitions[-1]["to"] = state.value

            elif state == AgentState.RESEARCH:
                answer_context = self.researcher.gather(query, route)
                sufficient, reason = self.researcher.is_evidence_sufficient(answer_context)

                if not sufficient and retries < self.max_retries:
                    retries += 1
                    refined = refine_query(query, reason, answer_context)
                    logger.info(
                        "Evidence insufficient (%s), retry %d/%d with refined query: %s",
                        reason, retries, self.max_retries, refined,
                    )
                    transitions[-1]["to"] = f"research_retry_{retries}"
                    query = refined  # update query for next loop iteration
                    state = AgentState.RESEARCH  # loop back to re-check
                else:
                    state = AgentState.SYNTHESIZE
                    transitions[-1]["to"] = state.value

            elif state == AgentState.SYNTHESIZE:
                prompt_bundle = self.synthesizer.render_prompt(answer_context)
                answer = self.synthesizer.synthesize(prompt_bundle, dry_run=dry_run)

                if curate:
                    state = AgentState.CURATE
                else:
                    state = AgentState.DONE
                transitions[-1]["to"] = state.value

            elif state == AgentState.CURATE:
                # Curate is optional and does not block completion
                state = AgentState.DONE
                transitions[-1]["to"] = state.value

        return {
            "query": query,
            "route": route,
            "pipeline_status": "dry_run" if dry_run else "complete",
            "state_transitions": transitions,
            "answer": answer.get("answer", answer.get("request_payload", {})),
            "citations": prompt_bundle.get("citations", []),
            "synthesis_meta": answer.get("synthesis_meta", {}),
        }
