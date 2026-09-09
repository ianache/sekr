---
date: 2026-09-07
document_type: Requirements Specification
owner: IA
status: Draft
title: Engineering Knowledge Runtime --- PoC v0.1 --- ReqSpec
version: 0.1
---

# Engineering Knowledge Runtime (SEKR) --- PoC v0.1

## Requirements Specification

## 1. Objetivo

Implementar una PoC ejecutable que compile contexto verificable para
agentes de desarrollo, detecte el impacto del cambio sobre el
conocimiento y valide un conjunto mínimo de reglas de
conocimiento/arquitectura.

## 2. Alcance funcional

### EPIC-01 --- Knowledge Model & Ingestion

**FR-001** El sistema SHALL ingerir un repositorio Git local
seleccionado.

**FR-002** SHALL procesar inicialmente código fuente, tests,
Markdown/README/ADR y un esquema SQL soportado por el caso de estudio.

**FR-003** SHALL excluir secretos, `.git`, dependencias descargadas,
builds, binarios y artefactos ignorados.

**FR-004** SHALL crear/actualizar en Neo4j entidades y relaciones del
modelo mínimo.

**FR-005** SHALL registrar procedencia de cada hecho derivado.

**AC:** dado el repositorio Tenant, una ingesta completa permite navegar
desde un Feature a código, tests, documentación y persistencia
relacionados cuando exista evidencia.

### EPIC-02 --- Context Compiler

**FR-010** SHALL exponer `compile_context(task)`.

**FR-011** SHALL interpretar intención y alcance de la tarea.

**FR-012** SHALL recuperar y rankear conocimiento relevante por tarea.

**FR-013** SHALL producir un `ContextPackage` estructurado.

**FR-014** SHALL incluir evidencia/procedencia y confidence por
elemento.

**FR-015** SHALL identificar contradicciones o ausencia de evidencia.

**FR-016** SHALL aceptar un presupuesto configurable de contexto.

**AC:** para la tarea experimental, el paquete identifica los artefactos
de referencia definidos por evaluación humana y evita incluir una
cantidad indiscriminada de archivos no relacionados.

### EPIC-03 --- Code & Impact Intelligence

**FR-020** SHALL definir `ProjectKnowledgeProvider`,
`CodeKnowledgeProvider` e `ImpactAnalysisProvider`.

**FR-021** SHALL desacoplar el dominio de Graphify, CodeGraph y
GitNexus.

**FR-022** SHALL soportar degradación explícita si un provider no está
disponible.

**FR-023** SHALL exponer `explain_symbol`, `trace_execution` y
`analyze_impact` cuando exista capacidad del provider.

### EPIC-04 --- Knowledge Delta

**FR-030** SHALL aceptar un `git diff` o rango Git.

**FR-031** SHALL identificar símbolos/artefactos modificados.

**FR-032** SHALL relacionar cambios con nodos/hechos del Knowledge
Graph.

**FR-033** SHALL marcar hechos/documentos potencialmente `STALE` sin
sobrescribirlos automáticamente.

**FR-034** SHALL identificar tests potencialmente afectados/faltantes.

**FR-035** SHALL proponer nuevos KnowledgeFacts derivados como
`INFERRED`.

**AC:** después del cambio experimental, el reporte Delta enumera código
modificado y al menos documentación, reglas o tests afectados definidos
en el oracle de evaluación.

### EPIC-05 --- Knowledge-as-Tests

**FR-040** SHALL permitir definir reglas versionadas.

**FR-041** SHALL ejecutar inicialmente 3--5 reglas.

**FR-042** SHALL retornar `PASS`, `FAIL`, `UNKNOWN` o `NOT_APPLICABLE`.

**FR-043** SHALL incluir evidencia utilizada para cada resultado.

**FR-044** SHALL distinguir fallo de regla de imposibilidad de
validación.

### EPIC-06 --- MCP Server

**FR-050** SHALL implementar un servidor MCP compatible con al menos un
harness seleccionado.

**FR-051** SHALL exponer: `compile_context`, `explain_symbol`,
`trace_execution`, `analyze_impact`, `calculate_knowledge_delta`,
`validate_knowledge`.

**FR-052** SHALL validar entradas y devolver errores estructurados.

**FR-053** SHALL evitar exponer secretos o contenido excluido.

### EPIC-07 --- Agent + Superpowers Workflow

**FR-060** SHALL integrarse con un harness inicial (Claude Code, Codex o
Antigravity).

**FR-061** SHALL documentar routing de SEKR en `AGENTS.md` y/o
instrucciones específicas del harness.

**FR-062** SHALL integrar Context Compiler antes del plan cuando la
tarea lo requiera.

**FR-063** SHALL ejecutar Knowledge Delta tras la implementación.

**FR-064** SHALL ejecutar Knowledge-as-Tests antes de
`verification-before-completion`.

### EPIC-08 --- Experimentation

**FR-070** SHALL permitir ejecutar un escenario baseline y uno SEKR.

**FR-071** SHALL capturar métricas definidas en el DRP.

**FR-072** SHALL guardar evidencia reproducible de cada ejecución.

**FR-073** SHALL generar un reporte comparativo final.

## 3. Contratos conceptuales

### ContextPackage

``` json
{
  "task": {},
  "requirements": [],
  "architecture": [],
  "symbols": [],
  "executionFlows": [],
  "persistence": [],
  "tests": [],
  "risks": [],
  "conflicts": [],
  "evidence": [],
  "contextBudget": {}
}
```

### KnowledgeDelta

``` json
{
  "change": {},
  "changedArtifacts": [],
  "affectedFacts": [],
  "potentiallyStale": [],
  "missingTests": [],
  "inferredKnowledge": [],
  "recommendedActions": []
}
```

### KnowledgeValidation

``` json
{
  "scope": "...",
  "results": [
    {"ruleId":"ARCH-002","status":"PASS","evidence":[]}
  ]
}
```

## 4. Modelo Neo4j v0.1

``` mermaid
graph LR
  R[Requirement] -->|IMPLEMENTS| F[Feature]
  F -->|IMPLEMENTED_BY| S[Symbol]
  F -->|EXPOSED_BY| E[Endpoint]
  F -->|PERSISTS_TO| T[Table]
  F -->|VERIFIED_BY| TS[Test]
  F -->|CONSTRAINED_BY| A[ADR]
  S -->|CALLS| S2[Symbol]
  KF[KnowledgeFact] -->|EVIDENCED_BY| D[Document]
  KF -->|ABOUT| F
  C[Change] -->|AFFECTS| S
  C -->|AFFECTS| KF
```

## 5. Requisitos no funcionales

**NFR-001 Reproducibilidad:** misma versión de repo/configuración deberá
producir resultados comparables.

**NFR-002 Trazabilidad:** todo hecho usado por el compiler deberá poder
remontarse a una fuente/evidencia.

**NFR-003 Seguridad:** secretos y rutas excluidas no deberán almacenarse
ni retornarse.

**NFR-004 Observabilidad:** operaciones principales deberán registrar
duración, providers usados y tamaño del contexto, sin registrar
secretos.

**NFR-005 Portabilidad:** núcleo de dominio no dependerá de APIs
específicas de Graphify/CodeGraph/GitNexus.

**NFR-006 Fail explicit:** ausencia/fallo de provider no podrá
presentarse como conocimiento verificado.

**NFR-007 Performance PoC:** `compile_context` sobre un repositorio ya
indexado deberá ser suficientemente interactivo para uso humano/agente;
se medirá p50/p95 sin fijar aún SLA productivo.

**NFR-008 Versionado:** reglas, hechos derivados y esquema de
conocimiento deberán incluir versión o timestamp de generación.

## 6. Seguridad y gobierno

-   Denylist/ignore de secrets, `.env`, llaves y credenciales.
-   No enviar fuentes a servicios externos sin autorización explícita.
-   KnowledgeFacts `APPROVED` requieren fuente aprobada; inferencias AI
    son `INFERRED`.
-   Delta no modifica automáticamente ADR o documentación aprobada.
-   Registrar provider y evidencia de resultados relevantes.

## 7. Caso experimental

Cambio de referencia: activación/desactivación de valores de Codificador
en Tenant, incluyendo filtrado de valores activos.

Oracle humano previo a la ejecución: - archivos/símbolos relevantes; -
dependencias esperadas; - tests esperados; - documentos/ADR afectados; -
reglas que deben pasar/fallar.

El oracle no se entregará al agente durante la ejecución.

## 8. Métricas

1.  Precision@K de artefactos recuperados.
2.  Recall de artefactos críticos.
3.  Tokens/context bytes suministrados.
4.  Archivos leídos fuera del Context Package.
5.  Recall de dependencias afectadas.
6.  Recall de tests relevantes.
7.  Drift detectado correctamente.
8.  Falsos positivos de Delta.
9.  Violaciones arquitectónicas detectadas.
10. Tiempo hasta plan aceptado.
11. Intervenciones humanas.

## 9. Matriz de trazabilidad

  -----------------------------------------------------------------------------
  Hipótesis            Requisitos        Prueba            Métrica
  -------------------- ----------------- ----------------- --------------------
  H1 Contexto          FR-010..016       Baseline vs SEKR  Precision@K, Recall,
  mínimo/preciso                                           tokens

  H2 Mejor impacto     FR-020..023       Cambio            dependencias/tests
                                         experimental      detectados

  H3 Knowledge Delta   FR-030..035       diff posterior    recall/falsos
                                                           positivos

  H4                   FR-040..044       reglas            PASS/FAIL correctos
  Knowledge-as-Tests                     controladas       
  -----------------------------------------------------------------------------

## 10. Definition of Done PoC

-   Ingesta reproducible del caso de estudio.
-   Grafo Neo4j inspeccionable.
-   `compile_context` operativo.
-   MCP operativo con un harness.
-   Knowledge Delta operativo.
-   3--5 Knowledge-as-Tests operativos.
-   Flujo completo con Superpowers ejecutado.
-   Baseline y SEKR ejecutados bajo condiciones documentadas.
-   Métricas y evidencias almacenadas.
-   Informe Go/Pivot/Stop producido.

## 11. Plan sugerido

-   P0: caso + oracle + hipótesis.
-   P1: ontología/modelo mínimo.
-   P2: ingesta + Neo4j.
-   P3: Context Compiler.
-   P4: MCP.
-   P5: Knowledge Delta.
-   P6: Knowledge-as-Tests.
-   P7: integración agente/Superpowers.
-   P8: experimento.
-   P9: evaluación y decisión.

## 12. Fuera de alcance

Portal web, multi-tenant productivo, Google Drive, ingesta universal,
RBAC enterprise, auto-aprobación de conocimiento, GraphRAG avanzado y
despliegue productivo.
