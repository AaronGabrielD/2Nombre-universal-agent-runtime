# M19 — Tool Registry + Orchestration

M19 integra M07 Tool Registry y M16 Tool Authorization dentro de M15. Los requisitos de herramientas y capacidades se resuelven antes de la ejecución; los requisitos desconocidos o no disponibles fallan en cerrado.

Las herramientas de alto riesgo o marcadas para aprobación humana abren Gate C. El worker entra en `WORKER_WAITING_HUMAN` antes de solicitar su plan de ejecución y antes de cruzar M08. Gate C queda vinculado a `run_id` y `worker_id`.

Una aprobación de Gate C permite reanudar exactamente el worker detenido. Un rechazo conduce a `REVISION`. Las solicitudes repetidas para el mismo worker y el mismo conjunto de herramientas reutilizan una Gate C compatible en lugar de crear duplicados.

M07/M16 nunca invocan directamente los handlers de herramientas. La ejecución continúa confinada a M08 y al backend configurado.
