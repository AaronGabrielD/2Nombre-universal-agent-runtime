"""Minimal Chainlit presentation adapter for the Universal Agent Runtime.

UI callbacks translate user actions into decisions for M05. They never mutate
workflow state directly and never execute tools or code.
"""
from __future__ import annotations

import os
from pathlib import Path

import chainlit as cl

from app.architect.service import UniversalArchitect
from app.core.contracts import HumanDecision, HumanDecisionType, to_dict
from app.core.config import get_settings
from app.intake.models import IntakeFile
from app.llm.gemini import GeminiAdapter
from app.runtime.service import RuntimeCoordinator, RuntimeCoordinatorError


settings = get_settings()
_coordinator = RuntimeCoordinator(
    architect=UniversalArchitect(GeminiAdapter(settings), settings=settings),
)


def _actor() -> str:
    user = cl.user_session.get("user")
    identifier = getattr(user, "identifier", None)
    return str(identifier or "human")


def _actions(gate_id: str, run_id: str, decisions: tuple[HumanDecisionType, ...]):
    return [
        cl.Action(
            name="runtime_gate_decision",
            payload={"gate_id": gate_id, "run_id": run_id, "decision": decision.value},
            label=label,
        )
        for decision, label in (
            (HumanDecisionType.APPROVE, "✅ Approve"),
            (HumanDecisionType.MODIFY, "✏️ Modify"),
            (HumanDecisionType.REJECT, "❌ Reject"),
            (HumanDecisionType.CLARIFY, "❓ Clarify"),
        )
        if decision in decisions
    ]


@cl.on_chat_start
async def on_chat_start() -> None:
    cl.user_session.set("run_id", None)
    await cl.Message(
        content=(
            "Universal Agent Runtime listo. Describe el objetivo del trabajo. "
            "Los cambios de arquitectura y la finalización siempre pasan por aprobación humana."
        ),
        author="Runtime",
    ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    run_id = cl.user_session.get("run_id")

    # A message without an active run starts a new runtime execution.
    if not run_id:
        files: list[IntakeFile] = []
        inline_text_by_name: dict[str, str] = {}
        for element in message.elements or []:
            path = getattr(element, "path", None)
            name = getattr(element, "name", None) or Path(path or "upload").name
            mime = getattr(element, "mime", None)
            if not path:
                continue
            size = os.path.getsize(path)
            inline_text = None
            if (mime or "").lower().startswith("text/") and size <= 256 * 1024:
                inline_text = Path(path).read_text(encoding="utf-8")
                inline_text_by_name[name] = inline_text
            files.append(
                IntakeFile(
                    name=name,
                    mime_type=mime,
                    size_bytes=size,
                    source_ref=path,
                    inline_text=inline_text,
                )
            )

        result = _coordinator.start_run(
            message.content,
            files=tuple(files),
            inline_text_by_name=inline_text_by_name,
        )
        cl.user_session.set("run_id", result.run_id)

        await cl.Message(
            content=f"Run creado: `{result.run_id}`\n\nConstruyendo arquitectura...",
            author="Runtime",
        ).send()

        try:
            checkpoint = await cl.make_async(_coordinator.build_architecture)(result.run_id)
        except Exception as exc:
            await cl.Message(
                content=f"No se pudo construir la arquitectura: `{exc}`",
                author="Runtime",
            ).send()
            return

        await cl.Message(
            content=(
                "## Arquitectura propuesta\n\n"
                f"```json\n{_json_text(to_dict(checkpoint.plan))}\n```\n\n"
                "Gate A: la ejecución está bloqueada hasta tu decisión."
            ),
            author="Architect",
            actions=_actions(
                checkpoint.gate_id,
                result.run_id,
                (
                    HumanDecisionType.APPROVE,
                    HumanDecisionType.MODIFY,
                    HumanDecisionType.REJECT,
                    HumanDecisionType.CLARIFY,
                ),
            ),
        ).send()
        return

    await cl.Message(
        content=(
            f"El run activo es `{run_id}`. Su estado actual es "
            f"`{_coordinator.sessions.get_context(run_id).state.value}`. "
            "Resuelve primero el gate mostrado en la interfaz."
        ),
        author="Runtime",
    ).send()


@cl.action_callback("runtime_gate_decision")
async def on_runtime_gate_decision(action: cl.Action) -> None:
    payload = action.payload or {}
    run_id = str(payload.get("run_id") or "")
    gate_id = str(payload.get("gate_id") or "")
    decision = HumanDecisionType(str(payload.get("decision") or ""))

    if decision in {HumanDecisionType.MODIFY, HumanDecisionType.CLARIFY}:
        response = await cl.AskUserMessage(
            content="Escribe la modificación o aclaración que debe tener en cuenta el runtime:",
            timeout=300,
        ).send()
        feedback = str((response or {}).get("output") or "").strip()
        if not feedback:
            await cl.Message(content="No se recibió feedback; el gate permanece sin aplicar.").send()
            return
    else:
        feedback = f"Human decision: {decision.value}"

    # The approval engine records the authoritative decision. The coordinator
    # then verifies that exact record before applying the state transition.
    try:
        recorded = _coordinator.approvals.resolve_gate(
            gate_id=gate_id,
            decision=decision,
            feedback=feedback,
            actor=_actor(),
        )
        state = _coordinator.apply_architecture_decision(recorded)
    except (ValueError, RuntimeCoordinatorError) as exc:
        await cl.Message(content=f"Decisión rechazada: `{exc}`", author="Runtime").send()
        return

    await cl.Message(
        content=f"Gate A resuelto como **{decision.value}**. Estado del run: `{state.value}`.",
        author="Human Approval",
    ).send()


def _json_text(value: object) -> str:
    import json
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)
