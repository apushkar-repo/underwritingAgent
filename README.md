# Underwriting Agent

A human-in-the-loop mortgage underwriting copilot built as composable LangGraph
subgraphs. Synthetic data only; this project does not make lending decisions.

## Phase 2: Document layer

The guided notebook version is available at
[`1_Document_Layer_Phase2.ipynb`](1_Document_Layer_Phase2.ipynb). It runs each
node independently and demonstrates missing-file and missing-evidence paths
with the three realistic intake packages. The compact eight-loan portfolio is
retained only for deterministic regression tests.

The first implemented subgraph follows this sequence:

```text
START
  -> document_intake
  -> classify_and_extract
  -> check_requirements
  -> END
```

- `document_intake` reads searchable PDFs and records extraction failures.
- `classify_and_extract` assigns a document type and extracts identifiers needed
  for routing and provenance.
- `check_requirements` compares the package with a deterministic inventory and
  identifies missing evidence inside otherwise-present documents.

The deterministic classifier keeps offline runs repeatable. When enabled,
`OpenAIDocumentInterpreter` performs structured classification and extraction
behind the same typed `ParsedDocument` boundary.

## Setup

```bash
uv sync
```

Run a clean package:

```bash
uv run python scripts/run_document_layer.py UW-26-0417-A
```

Run the missing-P&L case:

```bash
uv run python scripts/run_document_layer.py BRK-90831
```

Run tests:

```bash
uv run pytest
```

## Phase 3: Borrower analysis

The notebook-first prototype is
[`2_Borrower_Analysis_Phase3.ipynb`](2_Borrower_Analysis_Phase3.ipynb). The
production subgraph routes to salaried, self-employed, or mixed-income analysis,
then runs asset verification and liability analysis.

```text
classify_borrower
  -> selected income specialist
  -> asset_verification
  -> liability_analysis
```

Run Phase 2 and Phase 3 together for one synthetic loan:

```bash
uv run python scripts/run_borrower_analysis.py WHL-77-2206
```

## Phases 4–7

The remaining notebook-first walkthroughs are:

- [`3_Property_Analysis_Phase4.ipynb`](3_Property_Analysis_Phase4.ipynb)
- [`3B_Property_Web_Research.ipynb`](3B_Property_Web_Research.ipynb)
- [`4_Calculations_and_Policy_Phase5.ipynb`](4_Calculations_and_Policy_Phase5.ipynb)
- [`5_Reconciliation_and_Exceptions_Phase6.ipynb`](5_Reconciliation_and_Exceptions_Phase6.ipynb)
- [`6_Underwriting_Summary_Phase7.ipynb`](6_Underwriting_Summary_Phase7.ipynb)

Their production modules are composed in this order:

```text
property_analysis
  -> optional address-only cited property web research
  -> deterministic financial calculations
  -> local guideline vector retrieval
  -> canonical fact reconciliation
  -> normalized exceptions and conditions
  -> evidence-backed human review package
```

The local guideline store creates 256-dimensional hashing embeddings. It is
reproducible and requires no API key, making policy retrieval suitable for unit
tests. It can later be replaced with OpenAI embeddings and a persistent vector
database while preserving the `PolicyRule` output contract.

Run the complete Phase 2–7 pipeline:

```bash
uv run python scripts/run_full_pipeline.py WHL-77-2206
```

The final package always requires a qualified human underwriter. It does not
produce autonomous approval or denial decisions.

## Parent orchestrator

[`7_Underwriting_Orchestrator.ipynb`](7_Underwriting_Orchestrator.ipynb)
demonstrates the checkpointed parent LangGraph, including both interrupt paths.
The production implementation is in `src/underwriting_agent/orchestrator.py`.

The parent graph composes each compiled phase as a node and owns:

- conditional routing after document review and exception reconciliation;
- checkpoint persistence keyed by `thread_id`;
- missing-document upload and resume;
- exception acknowledgement or change requests;
- delivery of the structured human-review package.

Run a non-interactive first pass:

```bash
uv run python scripts/run_orchestrator.py UW-26-0417-A
uv run python scripts/run_orchestrator.py WHL-77-2206
```

Both examples can produce an interrupt payload when missing evidence or an
exception requires human review. The notebook demonstrates both resume paths.

## Optional OpenAI, Pinecone, and You.com services

Copy `.env.example` to `.env` and add credentials. All integrations are off by
default, so notebooks and tests remain runnable without network access.

```bash
cp .env.example .env
```

OpenAI can be enabled at three bounded locations:

- `USE_OPENAI_DOCUMENT_MODEL=true` uses strict structured output to classify
  and extract explicitly stated document facts.
- `USE_OPENAI_REVIEW_NARRATOR=true` drafts reviewer-facing prose from already
  verified facts, rules, exceptions, and conditions.
- `GUIDELINE_VECTOR_BACKEND=pinecone` uses OpenAI embeddings for persistent
  guideline retrieval in Pinecone.

The model does not calculate income, assets, debts, DTI, or LTV; enforce policy;
or approve/deny a loan. Those operations remain deterministic.

For persistent guideline vectors:

```dotenv
GUIDELINE_VECTOR_BACKEND=pinecone
PINECONE_API_KEY=...
OPENAI_API_KEY=...
```

Then create or refresh the index:

```bash
uv run python scripts/index_guidelines_pinecone.py
```

Pinecone stores OpenAI dense embeddings plus rule metadata under stable rule
IDs. The local hashing vector store remains the default test backend.

Run the orchestrator with enabled services:

```bash
uv run python scripts/run_orchestrator.py UW-26-0417-A --services-from-env
```

SQLite is intentionally not included; checkpointing still uses `InMemorySaver`.

## Streamlit frontend

The reviewer workspace supports realistic sample packages, temporary PDF
uploads, missing-document resumes, exception review, canonical evidence,
policy rules, and cited property research. Custom uploads receive a package
review screen listing every document before analysis. The final recommendation
also includes a timestamped activity log that distinguishes AI actions from
human uploads and review decisions.

Start it from the project root:

```bash
uv run streamlit run streamlit_app.py
```

Open `http://localhost:8501`. Optional OpenAI, Pinecone, and You.com services
are selected automatically from server-side `.env` feature flags. Credentials
and environment controls are not exposed to reviewers in the UI.

## Optional property web research

Phase 4B can use You.com's Web Search API to research the subject property's
public sale, listing, assessment, and online valuation history. Only the
property address is included in search queries. Borrower identity, financial
facts, credit data, account information, documents, and loan identifiers are
never sent to You.com.

Configure `.env`:

```env
YDC_API_KEY=your-key
USE_PROPERTY_WEB_RESEARCH=true
```

Then run:

```bash
uv run python scripts/run_full_pipeline.py UW-26-0417-A --services-from-env
```

Web observations and citations are included in
`external_property_research` in the final review package. They may create a
human-review discrepancy but never replace the appraisal or alter calculated
LTV.
