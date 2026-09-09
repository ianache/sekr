---
date: 2026-09-07
document_type: DRP
owner: IA
status: Draft
title: Engineering Knowledge Runtime --- PoC v0.1 --- DRP
version: 0.1
---

# Engineering Knowledge Runtime (SEKR) --- PoC v0.1

## Design & Research Proposal (DRP)

## 1. Propósito

Validar una forma de conocimiento aplicado al desarrollo de software con
IA que vaya más allá de RAG: entregar al agente el **contexto mínimo,
vigente, trazable y verificable** para una tarea concreta y detectar,
después de un cambio, qué conocimiento quedó afectado o dejó de ser
cierto.

## 2. Problema

Los agentes de coding suelen consumir contexto mediante lectura masiva
de archivos, búsqueda textual o recuperación semántica. Esto introduce
ruido, aumenta tokens, no garantiza vigencia y separa el cambio de
código de la actualización del conocimiento del proyecto.

## 3. Tesis

> Mejor contexto no significa más contexto. Un agente debería recibir el
> conocimiento mínimo suficiente para tomar una decisión de ingeniería,
> con evidencia, procedencia y nivel de confianza; cada cambio de
> software debería producir además un Knowledge Delta verificable.

## 4. Hipótesis de la PoC

**H1. Precisión contextual:** SEKR identifica más artefactos realmente
relevantes usando menos contexto que un agente baseline.

**H2. Impacto:** SEKR mejora la detección de dependencias, tests y
documentación afectados antes de implementar.

**H3. Conocimiento vivo:** a partir de un `git diff`, SEKR identifica
conocimiento potencialmente obsoleto y conocimiento nuevo.

**H4. Conocimiento verificable:** reglas arquitectónicas y de dominio
seleccionadas pueden expresarse como Knowledge-as-Tests y contrastarse
con código/grafo/esquema.

## 5. Caso de estudio inicial

Microservicio **Tenant**, escenario **Codificadores**. El cambio
experimental será suficientemente transversal para afectar API, dominio,
persistencia, tests y documentación. Ejemplo: habilitar
activación/desactivación de valores individuales y garantizar que las
consultas activas excluyan valores inactivos.

## 6. Diferenciadores

1.  **Context Compiler**, no simple búsqueda: compila un paquete
    orientado a tarea.
2.  **Evidence-aware knowledge**: hechos con fuente, evidencia, vigencia
    y confianza.
3.  **Knowledge Delta**: relaciona cambios de código con conocimiento
    afectado.
4.  **Knowledge-as-Tests**: conocimiento/arquitectura parcialmente
    ejecutable.
5.  **Provider abstraction**: Graphify, CodeGraph y GitNexus son
    sensores intercambiables, no el dominio de SEKR.
6.  **Feedback loop**: Knowledge → Agent → Change → Validate →
    Knowledge.

## 7. Principios

-   Minimum sufficient context.
-   Source of Truth antes que inferencia.
-   Evidencia antes que confianza declarada.
-   No ocultar contradicciones: marcarlas como `CONFLICTED`.
-   No actualizar conocimiento aprobado automáticamente sin política
    explícita.
-   Separar hechos derivados de decisiones aprobadas.
-   Adapters sobre herramientas concretas.
-   Seguridad por exclusión de secretos y datos no autorizados.

## 8. Arquitectura conceptual

``` mermaid
flowchart LR
  S[Git / Code / Tests / Docs / ADR / Schema] --> I[Knowledge Ingestion]
  I --> KG[(Neo4j Knowledge Graph)]
  G[Graphify Adapter] --> CC
  C[CodeGraph Adapter] --> CC
  N[GitNexus Adapter] --> CC
  KG --> CC[Context Compiler]
  CC --> MCP[MCP Server]
  MCP --> A[Claude Code / Codex / Antigravity]
  A --> SP[Superpowers Workflow]
  SP --> D[Code Change / git diff]
  D --> KD[Knowledge Delta]
  D --> KT[Knowledge-as-Tests]
  KD --> KG
  KT --> KG
```

## 9. Modelo mínimo de conocimiento

Entidades iniciales: `Requirement`, `Feature`, `Component`, `Symbol`,
`Endpoint`, `Table`, `Test`, `ADR`, `Document`, `KnowledgeFact`,
`KnowledgeRule`, `Change`.

Relaciones iniciales: `IMPLEMENTS`, `IMPLEMENTED_BY`, `EXPOSED_BY`,
`PERSISTS_TO`, `VERIFIED_BY`, `CONSTRAINED_BY`, `DEPENDS_ON`, `CALLS`,
`DOCUMENTED_BY`, `AFFECTS`, `EVIDENCED_BY`.

### KnowledgeFact

Campos mínimos: - `id` - `statement` - `source` - `sourceVersion` -
`evidence[]` - `confidence`:
`VERIFIED | APPROVED | INFERRED | STALE | CONFLICTED | UNKNOWN` -
`freshness` - `validFrom` - `scope` - `owner` (si aplica)

## 10. Context Compiler

Entrada: tarea/intención del agente.

Salida: `ContextPackage` con: - task interpretation; - requirements; -
architectural constraints; - relevant symbols; - execution paths; -
persistence/schema; - relevant tests; - risks; - evidence/provenance; -
confidence; - unresolved conflicts.

El compiler deberá priorizar relevancia y evidencia y aplicar un
presupuesto configurable de contexto.

## 11. Knowledge Delta

Entrada: `git diff` o conjunto de cambios.

Salida: - símbolos y artefactos cambiados; - hechos afectados; -
documentación/ADR potencialmente stale; - tests potencialmente
faltantes; - conocimiento nuevo inferido; - acciones propuestas.

La PoC **propone** actualizaciones; no modifica automáticamente
decisiones aprobadas.

## 12. Knowledge-as-Tests

La PoC implementará 3--5 reglas. Ejemplos: - `CODER-001`: consultas de
valores activos no devuelven valores inactivos. - `ARCH-002`: Controller
no accede directamente a Repository. - `ARCH-003`: un CoderValue
pertenece exactamente a un Coder.

Estados: `PASS | FAIL | UNKNOWN | NOT_APPLICABLE`.

## 13. Tool Providers

Interfaces conceptuales: - `ProjectKnowledgeProvider` -
`CodeKnowledgeProvider` - `ImpactAnalysisProvider` -
`SemanticSearchProvider` (opcional v0.1)

Graphify, CodeGraph y GitNexus se integrarán mediante adapters cuando
estén disponibles. La PoC deberá seguir operando parcialmente si un
provider no está disponible.

## 14. MCP

Operaciones objetivo: - `compile_context(task)` -
`explain_symbol(symbol)` - `trace_execution(feature)` -
`analyze_impact(change)` - `calculate_knowledge_delta(diff)` -
`validate_knowledge(scope)`

## 15. Flujo con Superpowers

``` mermaid
flowchart LR
  B[Brainstorm] --> C[Compile Context]
  C --> P[Writing Plan]
  P --> IA[Impact Analysis]
  IA --> T[TDD]
  T --> I[Implement]
  I --> KD[Knowledge Delta]
  KD --> V[Validate Knowledge]
  V --> VC[Verification Before Completion]
  VC --> F[Finish]
```

## 16. Experimento

Dos ejecuciones equivalentes: - **Baseline:** agente/harness sin SEKR. -
**Treatment:** mismo harness/modelo con SEKR.

Mantener constantes, en lo posible, repositorio, tarea, modelo,
instrucciones y entorno.

### Métricas

-   tokens/contexto consumido;
-   archivos leídos;
-   precisión de artefactos relevantes;
-   dependencias afectadas detectadas;
-   tests relevantes detectados;
-   drift de conocimiento detectado;
-   errores arquitectónicos introducidos;
-   tiempo hasta plan técnicamente aceptable;
-   intervención humana requerida.

## 17. Criterios de éxito

La PoC será prometedora si demuestra mejora material en
precisión/impacto sin aumentar indiscriminadamente contexto, y si
Knowledge Delta/Knowledge-as-Tests detectan al menos casos reales que el
baseline no identifica.

## 18. Go / Pivot / Stop

**GO:** Context Compiler aporta precisión medible y Delta/Tests producen
señales accionables.

**PIVOT:** el grafo aporta valor pero el compiler no supera estrategias
simples; revisar ontología/ranking/providers.

**STOP:** el costo operacional/contextual supera el beneficio o los
resultados no son reproducibles.

## 19. Fuera de alcance v0.1

Portal web, multi-producto, RBAC enterprise, Google Drive, ingesta
masiva de PDF, observabilidad productiva, actualización autónoma de ADR,
ontología visual, GraphRAG avanzado y operación productiva multi-tenant.

## 20. Roadmap posterior

v0.2: más fuentes/providers, versionado temporal, Qdrant si aporta
valor, GitLab Issues/PR, OKF como formato portable y políticas de
aprobación humana.

v0.3+: Engineering Memory causal, observabilidad/incident knowledge,
knowledge drift continuo y gobierno multi-producto.
