"""Chainlit presentation adapter for the Universal Agent Runtime.

UI callbacks translate user actions into runtime operations. They do not own
workflow state, provider logic, tool execution, or execution-backend internals.
"""
from __future__ import annotations

import json
from pathlib import Path

import chainlit as cl

from app.core.contracts import HumanDecisionType, to_dict
from app.core.states import WorkflowState
from app.intake.models import IntakeFile
from app.runtime import RuntimeApplication, RuntimeCoordinatorError, build_runtime
from app.identity import RunAccessDeniedError


_runtime: RuntimeApplication = build_runtime()
_coordinator = _runtime.coordinator
_orchestrator = _runtime.orchestrator
_identity_service = _runtime.identity
_run_authorization = _runtime.run_authorization


@cl.password_auth_callback
def password_auth_callback(username: str, password: str):
    """Authenticate against durable SQLite identity storage."""
    identity = _identity_service.authenticate(username, password)
    if identity is None:
        return None
    return cl.User(
        identifier=identity.username,
        metadata={**identity.metadata(), "user_id": identity.user_id},
    )


def _identity():
    user = cl.user_session.get("user")
    metadata = getattr(user, "metadata", {}) or {}
    user_id = str(metadata.get("user_id") or "").strip()
    role = str(metadata.get("role") or "user").strip()
    identifier = str(getattr(user, "identifier", "") or "").strip()
    if not user_id or not identifier:
        raise RuntimeCoordinatorError("authenticated identity is missing required metadata")
    try:
        identity = _identity_service.get_identity(user_id)
    except ValueError as exc:
        raise RuntimeCoordinatorError(str(exc)) from exc
    if identity.username != identifier or identity.role.value != role:
        raise RuntimeCoordinatorError("authenticated identity metadata mismatch")
    return identity


def _actor() -> str:
    return _identity().username


def _require_run_access(run_id: str):
    identity = _identity()
    context = _coordinator.sessions.get_context(run_id)
    try:
        _run_authorization.require_access(identity, context)
    except RunAccessDeniedError as exc:
        raise RuntimeCoordinatorError(str(exc)) from exc
    return context


def _actions(
    gate_id: str,
    run_id: str,
    decisions: tuple[HumanDecisionType, ...],
    *,
    worker_id: str | None = None,
):
    labels = {
        HumanDecisionType.APPROVE: "✅ Approve",
        HumanDecisionType.MODIFY: "✏️ Modify",
        HumanDecisionType.REJECT: "❌ Reject",
        HumanDecisionType.CLARIFY: "❓ Clarify",
    }
    return [
        cl.Action(
            name="runtime_gate_decision",
            payload={
                "gate_id": gate_id,
                "run_id": run_id,
                "worker_id": worker_id,
                "decision": decision.value,
            },
            label=labels[decision],
        )
        for decision in decisions
    ]


async def _show_architecture_gate(checkpoint) -> None:
    await cl.Message(
        content=(
            "## Arquitectura propuesta\n\n"
            f"```json\n{_json_text(to_dict(checkpoint.plan))}\n```\n\n"
            "Gate A: la ejecución está bloqueada hasta tu decisión."
        ),
        author="Architect",
        actions=_actions(
            checkpoint.gate_id,
            checkpoint.run_id,
            (
                HumanDecisionType.APPROVE,
                HumanDecisionType.MODIFY,
                HumanDecisionType.REJECT,
                HumanDecisionType.CLARIFY,
            ),
        ),
    ).send()


async def _show_final_gate(gate_id: str, run_id: str) -> None:
    gate = _runtime.approvals.get_gate(gate_id)
    await cl.Message(
        content=(
            "## Gate D — aprobación final\n\n"
            "El Supervisor aprobó el resultado. La finalización sigue bloqueada hasta tu decisión."
        ),
        author="Human Approval",
        actions=_actions(gate.gate_id, run_id, gate.allowed_decisions),
    ).send()


async def _show_tool_gate(gate_id: str, run_id: str, worker_id: str | None) -> None:
    gate = _runtime.approvals.get_gate(gate_id)
    await cl.Message(
        content=(
            "## Gate C — autorización requerida\n\n"
            f"El worker `{worker_id}` solicita acceso a una herramienta de riesgo.\n\n"
            f"```json\n{_json_text(gate.context)}\n```"
        ),
        author="Human Approval",
        actions=_actions(
            gate.gate_id,
            run_id,
            gate.allowed_decisions,
            worker_id=worker_id,
        ),
    ).send()


async def _run_orchestration(run_id: str) -> None:
    try:
        result = await cl.make_async(_orchestrator.execute_run)(run_id)
    except Exception as exc:
        await cl.Message(content=f"No se pudo ejecutar el run: `{exc}`", author="Runtime").send()
        return

    if result.pending_gate_id:
        await _show_tool_gate(result.pending_gate_id, run_id, result.pending_worker_id)
        return

    if result.qa_result is not None:
        await cl.Message(
            content=(
                f"### Supervisor / QA\n\n**{result.qa_result.status.value.upper()}**\n\n"
                f"{result.qa_result.summary}"
            ),
            author="Supervisor",
        ).send()

    if result.final_gate_id:
        await _show_final_gate(result.final_gate_id, run_id)
    elif result.qa_result is not None:
        state = _coordinator.sessions.get_context(run_id).state
        await cl.Message(
            content=f"Estado del run: `{state.value}`. QA no pasó; el flujo queda en revisión.",
            author="Runtime",
        ).send()


@cl.on_chat_start
async def on_chat_start() -> None:
    cl.user_session.set("run_id", None)
    identity = _identity()
    await cl.Message(
        content=(
            f"Universal Agent Runtime listo para `{identity.username}` ({identity.role.value}). "
            "Describe el objetivo del trabajo. Los cambios de arquitectura, acciones de riesgo "
            "y la finalización siempre pasan por aprobación humana."
        ),
        author="Runtime",
    ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    try:
        identity = _identity()
    except RuntimeCoordinatorError as exc:
        await cl.Message(content=f"Autenticación no disponible: `{exc}`", author="Runtime").send()
        return

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
            size = Path(path).stat().st_size
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
                metadata=_run_authorization.owner_metadata(identity),
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

        await _show_architecture_gate(checkpoint)
        return

    try:
        context = _require_run_access(run_id)
    except (RuntimeCoordinatorError, ValueError) as exc:
        await cl.Message(content=f"Acceso al run rechazado: `{exc}`", author="Runtime").send()
        cl.user_session.set("run_id", None)
        return

    await cl.Message(
        content=f"El run activo es `{run_id}` y está en `{context.state.value}`.",
        author="Runtime",
    ).send()


@cl.action_callback("runtime_gate_decision")
async def on_runtime_gate_decision(action: cl.Action) -> None:
    payload = action.payload or {}
    run_id = str(payload.get("run_id") or "")
    gate_id = str(payload.get("gate_id") or "")
    worker_id = str(payload.get("worker_id") or "") or None
    decision_value = str(payload.get("decision") or "")

    if not run_id or not gate_id:
        await cl.Message(content="Gate inválido: faltan identificadores.", author="Runtime").send()
        return

    try:
        _require_run_access(run_id)
        decision = HumanDecisionType(decision_value)
        gate = _runtime.approvals.get_gate(gate_id)
        if gate.run_id != run_id:
            raise RuntimeCoordinatorError("gate/run ownership mismatch")

        if gate.kind == "TOOL_RISK":
            if not worker_id:
                raise RuntimeCoordinatorError("tool-risk gate is missing worker_id")
            authorization = await cl.make_async(_orchestrator.resume_after_tool_gate)(
                run_id=run_id,
                gate_id=gate_id,
                decision=decision,
                worker_id=worker_id,
                feedback=f"Human decision: {decision.value}",
                actor=_actor(),
            )
            await cl.Message(
                content=f"Gate C resuelto como **{decision.value}**. Reanudando `{worker_id}`...",
                author="Human Approval",
            ).send()
            if authorization.pending_gate_id:
                await _show_tool_gate(
                    authorization.pending_gate_id,
                    run_id,
                    authorization.pending_worker_id,
                )
            elif authorization.final_gate_id:
                await _show_final_gate(authorization.final_gate_id, run_id)
            return

        if gate.kind not in {"ARCHITECTURE", "FINAL"}:
            raise RuntimeCoordinatorError(f"unsupported gate kind: {gate.kind}")

        if decision in {HumanDecisionType.MODIFY, HumanDecisionType.CLARIFY}:
            feedback = await _request_feedback()
            if not feedback:
                await cl.Message(content="No se recibió feedback; no se aplicó la decisión.").send()
                return
        else:
            feedback = f"Human decision: {decision.value}"

        recorded = _runtime.approvals.resolve_gate(
            gate_id=gate_id,
            decision=decision,
            feedback=feedback,
            actor=_actor(),
        )
        if gate.kind == "ARCHITECTURE":
            state = _coordinator.apply_architecture_decision(recorded)
        else:
            state = _coordinator.apply_final_decision(recorded)
    except (ValueError, RuntimeCoordinatorError, RunAccessDeniedError) as exc:
        await cl.Message(content=f"Decisión rechazada: `{exc}`", author="Runtime").send()
        return

    await cl.Message(
        content=f"Gate `{gate.kind}` resuelto como **{decision.value}**. Estado del run: `{state.value}`.",
        author="Human Approval",
    ).send()

    if gate.kind == "ARCHITECTURE":
        if state == WorkflowState.EXECUTING:
            await _run_orchestration(run_id)
        elif state == WorkflowState.ARCHITECTING:
            try:
                checkpoint = await cl.make_async(_coordinator.build_architecture)(
                    run_id,
                    context={"human_feedback": feedback},
                )
                await _show_architecture_gate(checkpoint)
            except Exception as exc:
                await cl.Message(content=f"No se pudo reconstruir la arquitectura: `{exc}`", author="Runtime").send()
    elif state == WorkflowState.COMPLETED:
        await cl.Message(content="✅ Run completado con aprobación humana final.", author="Runtime").send()
    elif state == WorkflowState.REVISION:
        await cl.Message(content="🔄 El run vuelve a revisión.", author="Runtime").send()
    elif state == WorkflowState.REJECTED:
        await cl.Message(content="🛑 El run fue rechazado y no continuará.", author="Runtime").send()


async def _request_feedback() -> str:
    response = await cl.AskUserMessage(
        content="Escribe la modificación o aclaración que debe tener en cuenta el runtime:",
        timeout=300,
    ).send()
    return str((response or {}).get("output") or "").strip()


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)
