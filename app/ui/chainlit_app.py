"""Minimal Chainlit presentation adapter for the Universal Agent Runtime.

UI callbacks translate user actions into decisions for M05. They never mutate
workflow state directly and never execute tools or code.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import chainlit as cl

from app.architect.service import UniversalArchitect
from app.core.contracts import HumanDecisionType, to_dict
from app.core.config import get_settings
from app.core.states import WorkflowState
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
    labels = {
        HumanDecisionType.APPROVE: "✅ Approve",
        HumanDecisionType.MODIFY: "✏️ Modify",
        HumanDecisionType.REJECT: "❌ Reject",
        HumanDecisionType.CLARIFY: "❓ Clarify",
    }
    return [
        cl.Action(
            name="runtime_gate_decision",
            payload={"gate_id": gate_id, "run_id": run_id, "decision": decision.value},
            label=labels[decision],
        )
        for decision in decisions
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

        try:
            result = _coordinator.start_run(
                message.content,
                files=tuple(files),
                inline_text_by_name=inline_text_by_name,
            )
            cl.user_session.set("run_id", result.run_id)
        except Exception as exc:
            await cl.Message(content=f"Entrada rechazada: `{exc}`", author="Runtime").send()
            return

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

    state = _coordinator.sessions.get_context(run_id).state
    await cl.Message(
        content=(
            f"El run activo es `{run_id}` y está en `{state.value}`. "
            "El siguiente avance depende del componente de ejecución/supervisión que todavía estamos integrando."
        ),
        author="Runtime",
    ).send()


@cl.action_callback("runtime_gate_decision")
async def on_runtime_gate_decision(action: cl.Action) -> None:
    payload = action.payload or {}
    run_id = str(payload.get("run_id") or "")
    gate_id = str(payload.get("gate_id") or "")
    decision_value = str(payload.get("decision") or "")

    if not run_id or not gate_id:
        await cl.Message(content="Gate inválido: faltan identificadores.", author="Runtime").send()
        return

    try:
        decision = HumanDecisionType(decision_value)
        gate = _coordinator.approvals.get_gate(gate_id)
        if gate.run_id != run_id:
            raise RuntimeCoordinatorError("gate/run ownership mismatch")

        if decision in {HumanDecisionType.MODIFY, HumanDecisionType.CLARIFY}:
            response = await cl.AskUserMessage(
                content="Escribe la modificación o aclaración que debe tener en cuenta el runtime:",
                timeout=300,
            ).send()
            feedback = str((response or {}).get("output") or "").strip()
            if not feedback:
                await cl.Message(content="No se recibió feedback; no se aplicó la decisión.").send()
                return
        else:
            feedback = f"Human decision: {decision.value}"

        recorded = _coordinator.approvals.resolve_gate(
            gate_id=gate_id,
            decision=decision,
            feedback=feedback,
            actor=_actor(),
        )
        if gate.kind == "ARCHITECTURE":
            state = _coordinator.apply_architecture_decision(recorded)
        elif gate.kind == "FINAL":
            state = _coordinator.apply_final_decision(recorded)
        else:
            raise RuntimeCoordinatorError(f"unsupported gate kind: {gate.kind}")
    except (ValueError, RuntimeCoordinatorError) as exc:
        await cl.Message(content=f"Decisión rechazada: `{exc}`", author="Runtime").send()
        return

    await cl.Message(
        content=f"Gate `{gate.kind}` resuelto como **{decision.value}**. Estado del run: `{state.value}`.",
        author="Human Approval",
    ).send()

    if state == WorkflowState.COMPLETED:
        await cl.Message(content="✅ Run completado con aprobación humana final.", author="Runtime").send()
    elif state == WorkflowState.REVISION:
        await cl.Message(content="🔄 El run vuelve a revisión; la siguiente etapa será replanificar.", author="Runtime").send()
    elif state == WorkflowState.REJECTED:
        await cl.Message(content="🛑 El run fue rechazado y no continuará.", author="Runtime").send()


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)
