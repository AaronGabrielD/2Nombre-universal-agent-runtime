# Universal Agent Runtime — Blueprint Maestro v1.0

## 0. Misión

Construir una plataforma web universal de agentes autónomos con:

- Chainlit como interfaz humana.
- CrewAI como orquestador de agentes y tareas.
- Gemini API como cerebro configurable.
- Human-in-the-Loop en puntos de control obligatorios.
- Worker Factory dinámica (3–4 workers concurrentes inicialmente).
- Tool Registry y Capability Registry.
- Execution Gateway desacoplado del backend de ejecución.
- Google Colab como primer backend experimental de ejecución.
- Vista previa HTML/CSS/JS dentro de Chainlit.
- Hosting desacoplado para poder usar Hugging Face si la modalidad disponible lo permite, o Render Free como ruta $0 alternativa.

## 1. Principios arquitectónicos

1. El usuario tiene autoridad máxima.
2. Ningún worker puede saltarse el Supervisor o los gates humanos.
3. Los agentes no conocen detalles de infraestructura que no necesitan.
4. El modelo LLM es configurable por variables de entorno.
5. Las herramientas se registran explícitamente antes de poder usarse.
6. El sistema muestra actividad operativa y resultados, no chain-of-thought privado.
7. Los archivos se tratan como entradas universales y se procesan mediante adaptadores.
8. El runtime debe poder cambiar Gemini, Colab, hosting o herramientas sin reescribir la orquestación.
9. Todo estado de ejecución debe tener un `run_id` único.
10. El sistema debe fallar de forma segura: error de herramienta ≠ aprobación automática.

## 2. Jerarquía

```text
HUMAN
  > SUPERVISOR
    > ARCHITECT
      > WORKER FACTORY
        > WORKERS
          > TOOLS
            > EXECUTION BACKENDS
```

## 3. Flujo canónico

```text
USER_INPUT
  -> INTAKE
  -> ARCHITECTURE
  -> HUMAN_GATE_ARCHITECT
  -> DISPATCH
  -> PARALLEL_WORKERS
  -> OPTIONAL_TOOL_EXECUTION
  -> SUPERVISION / QA
  -> HUMAN_GATE_FINAL
  -> COMPLETE | REVISE | REJECT
```

## 4. Máquina de estados de una ejecución

Estados mínimos:

- `IDLE`
- `INTAKE`
- `ARCHITECTING`
- `WAITING_ARCHITECT_APPROVAL`
- `EXECUTING`
- `WORKER_WAITING_HUMAN`
- `SUPERVISING`
- `WAITING_FINAL_APPROVAL`
- `REVISION`
- `COMPLETED`
- `REJECTED`
- `FAILED`

Transiciones ilegales deben ser rechazadas por el `SessionManager`.

## 5. Módulos

### M00 — Foundation & Contracts

Responsabilidad:
- Configuración central.
- Tipos/DTOs.
- Contratos JSON.
- IDs y estados.
- Logging estructurado.
- Manejo de errores.

No contiene lógica específica de UI ni de proveedores.

### M01 — Session Manager

Responsabilidad:
- Crear/destruir `run_id`.
- Mantener estado de la ejecución.
- Guardar mensajes, archivos, decisiones y resultados.
- Proteger aislamiento entre ejecuciones y workers.

### M02 — Universal Intake

Responsabilidad:
- Recibir objetivo del usuario.
- Recibir archivos.
- Registrar metadata.
- Determinar estrategia de ingestión:
  - inline text
  - Gemini Files API
  - parser local
  - binario no interpretado

No decide la solución del problema.

### M03 — Gemini Adapter

Responsabilidad:
- Encapsular SDK/API de Gemini.
- Selección de modelo por rol.
- Timeouts/reintentos.
- Conteo de uso cuando esté disponible.
- Formateo uniforme de respuestas.

Modelos por defecto deben ser variables de entorno; nunca hardcodear nombres antiguos.

### M04 — Universal Architect

Responsabilidad:
- Analizar objetivo + contexto.
- Crear estrategia.
- Crear criterios de aceptación.
- Proponer workers.
- Declarar herramientas necesarias.
- Identificar riesgos y dependencias.

Salida obligatoria: `ArchitecturePlan` estructurado.

### M05 — Human Approval Engine

Responsabilidad:
- Implementar los gates humanos.
- Gate de arquitectura.
- Solicitudes de aclaración de worker.
- Gate final.
- Registrar decisión, autor, timestamp y feedback.

CrewAI debe recibir `human_input=True` en las tareas donde aplique, pero la interacción se canaliza a Chainlit mediante un proveedor/UI bridge.

### M06 — Worker Factory & Dispatcher

Responsabilidad:
- Crear workers dinámicamente desde `ArchitecturePlan`.
- Límite inicial: 3–4 workers concurrentes.
- Asignar contexto mínimo necesario a cada worker.
- Publicar estado de cada worker.
- Ejecutar en paralelo.

### M07 — Tool Registry & Capability Registry

Responsabilidad:
- Registrar herramientas disponibles.
- Describir capacidades y restricciones.
- Validar que una herramienta exista antes de planificarla.
- Definir permisos por herramienta.

### M08 — Execution Gateway

Responsabilidad:
- Exponer una interfaz estable como `execute(request)`.
- NO depender directamente de Colab.
- Devolver `ExecutionResult` uniforme.
- Aplicar límites, timeout y permisos.

Backend inicial: `ColabExecutionBackend` experimental.

### M09 — Supervisor & QA

Responsabilidad:
- Recibir outputs de workers.
- Compararlos con el plan arquitectónico.
- Ejecutar pruebas a través de Execution Gateway cuando sea necesario.
- Analizar stdout/stderr/exit code.
- Solicitar correcciones.
- Producir `FinalResult`.

### M10 — Preview & UI Presentation

Responsabilidad:
- Steps de Chainlit.
- Estado por worker.
- Elementos de visualización.
- Preview HTML/CSS/JS.
- Renderizado seguro en sandbox/iframe.

### M11 — Deployment Adapter

Responsabilidad:
- Dockerfile.
- Configuración del puerto.
- Variables/secrets.
- Health check.
- Documentación de despliegue.

Targets iniciales:
1. Render Free.
2. Hugging Face Docker si la cuenta/modalidad lo permite.

## 6. Contratos principales

### 6.1 ArchitecturePlan

```json
{
  "plan_id": "string",
  "objective": "string",
  "assumptions": ["string"],
  "constraints": ["string"],
  "acceptance_criteria": ["string"],
  "risks": ["string"],
  "required_capabilities": ["string"],
  "workers": [
    {
      "worker_id": "string",
      "role": "string",
      "mission": "string",
      "deliverables": ["string"],
      "required_tools": ["string"],
      "dependencies": ["worker_id"],
      "can_request_human_input": true
    }
  ]
}
```

### 6.2 ToolSpec

```json
{
  "tool_id": "string",
  "name": "string",
  "description": "string",
  "input_schema": {},
  "output_schema": {},
  "risk_level": "low|medium|high",
  "requires_human_approval": false,
  "available": true
}
```

### 6.3 ExecutionRequest

```json
{
  "execution_id": "string",
  "run_id": "string",
  "worker_id": "string",
  "language": "python",
  "code": "string",
  "timeout_seconds": 60,
  "needs_network": false
}
```

### 6.4 ExecutionResult

```json
{
  "execution_id": "string",
  "status": "success|error|timeout|denied|unavailable",
  "exit_code": 0,
  "stdout": "string",
  "stderr": "string",
  "duration_ms": 0,
  "artifacts": [],
  "backend": "colab"
}
```

### 6.5 HumanDecision

```json
{
  "gate_id": "string",
  "run_id": "string",
  "decision": "approve|modify|reject|clarify",
  "feedback": "string",
  "timestamp": "ISO-8601"
}
```

### 6.6 FinalResult

```json
{
  "run_id": "string",
  "status": "ready|needs_revision|rejected|failed",
  "summary": "string",
  "deliverables": [],
  "tests": [],
  "issues": [],
  "recommended_next_action": "string"
}
```

## 7. Reglas de concurrencia

- Máximo configurable: `MAX_WORKERS=4`.
- Mínimo deseado: `MIN_WORKERS=3` cuando el plan tenga suficiente paralelismo.
- No crear workers adicionales por iniciativa del modelo sin pasar por Dispatcher.
- Cada worker tiene identidad, estado y contexto aislado.
- Un worker bloqueado esperando humano no debe bloquear workers independientes.

## 8. Reglas de Human-in-the-Loop

### Gate A — Architecture

No se permite iniciar workers antes de una decisión humana `approve`.

`modify` => el Architect revisa el plan.

`reject` => run termina en `REJECTED`.

### Gate B — Worker clarification

Un worker puede solicitar aclaración sin detener workers no dependientes.

### Gate C — Risky execution

Una herramienta `risk_level=high` debe pedir aprobación antes de ejecutar.

### Gate D — Final

El Supervisor no puede declarar el run completado como éxito final sin `approve` humano.

## 9. Herramientas iniciales

Tier 0 (seguras):
- file_metadata
- text_extract
- json_validate
- html_preview
- calculator

Tier 1 (sandbox):
- python_execute -> Execution Gateway

Tier 2 (futuro):
- web_search
- browser
- git
- shell sandbox

Nunca implementar Tier 2 directamente en M00–M03.

## 10. Política de archivos

El sistema debe aceptar cualquier MIME en la UI, pero la semántica se determina por adaptadores.

Prioridad de ingestión:

1. Gemini Files API cuando convenga.
2. Parser local especializado si aporta más control.
3. Metadata + referencia si es un binario aún no soportado.

No prometer que todos los formatos tienen comprensión semántica inmediata.

## 11. Observabilidad

Cada evento debe incluir:

- timestamp
- run_id
- component
- agent_id cuando aplique
- event_type
- status
- short_message

Ejemplos:

- `architect.started`
- `architect.plan_ready`
- `human.gate_requested`
- `human.gate_resolved`
- `worker.started`
- `worker.progress`
- `worker.human_requested`
- `tool.called`
- `execution.completed`
- `supervisor.qa_started`
- `supervisor.final_ready`

## 12. Seguridad mínima

- API keys únicamente en environment/secrets.
- Nunca imprimir secrets en logs.
- Sanitizar nombres de archivos.
- Limitar tamaño de uploads.
- Limitar tiempo de ejecución.
- No ejecutar código arbitrario dentro del web container cuando exista Execution Gateway.
- Colab se considera backend remoto, no sandbox de seguridad absoluta.
- Los resultados externos se tratan como datos no confiables.

## 13. Estrategia de modelos

Variables previstas:

```text
GEMINI_API_KEY
GEMINI_MODEL_ARCHITECT
GEMINI_MODEL_WORKER
GEMINI_MODEL_SUPERVISOR
GEMINI_TEMPERATURE
```

La aplicación debe permitir cambiar modelos sin modificar código.

## 14. Hosting

### Objetivo de costo

$0 cuando sea posible, respetando límites reales de cada plataforma.

### Ruta primaria PoC

Render Free:
- web service $0
- puede desplegar Docker
- sleep tras inactividad
- filesystem efímero
- 750 horas Free incluidas por workspace/mes según documentación actual

### Ruta alternativa

Hugging Face Docker sólo si el plan/cuenta permite crear y ejecutar el Space; la documentación actual indica que Docker Spaces que ejecutan cómputo requieren plan de pago para cuentas personales.

## 15. Orden de implementación

1. M00
2. M01
3. M03
4. M04
5. M05
6. M06
7. M07
8. M08
9. M09
10. M10
11. M02 endurecido
12. M11
13. Integración completa

## 16. Criterio de finalización del Blueprint

El Blueprint se considera aprobado cuando:

- Todos los módulos tienen una responsabilidad única.
- Los contratos no contienen detalles de UI innecesarios.
- El Execution Gateway no depende de Colab.
- Gemini está detrás de un adapter.
- Human approval tiene contrato propio.
- La creación de workers es dinámica.
- Se puede sustituir el hosting.

## 17. Regla de liderazgo del proyecto

No añadir una funcionalidad grande a `app.py` sólo porque "funciona".

Cada capacidad nueva debe decidirse primero en qué módulo pertenece y qué contrato la conecta con el resto.
