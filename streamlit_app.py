"""Streamlit reviewer workspace for the mortgage underwriting copilot."""

from __future__ import annotations

import sys
import tempfile
import uuid
from pathlib import Path

import streamlit as st
from langgraph.types import Command
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from underwriting_agent.integrations import build_integrations_from_env
from underwriting_agent.intake_packages import (
    available_intake_references,
    resolve_document_paths,
)
from underwriting_agent.orchestrator import build_underwriting_orchestrator
from underwriting_agent.ui_support import (
    fact_map,
    format_money,
    format_percent,
    save_uploaded_pdfs,
)


PDF_ROOT = PROJECT_ROOT / "data" / "realistic_pdfs"
GUIDELINES = PROJECT_ROOT / "data" / "underwriting_guidelines.jsonl"
load_dotenv(PROJECT_ROOT / ".env", override=False)
SAMPLE_LABELS = {
    "UW-26-0417-A": "Elena Moreno · salaried purchase",
    "BRK-90831": "Marcus Hayes · self-employed",
    "WHL-77-2206": "Priya & Daniel Nguyen · mixed income",
}
RECOMMENDATION_LABELS = {
    "standard_human_review": "Standard human review",
    "conditional_review": "Conditional review recommended",
    "escalated_review": "Escalated review recommended",
    "suspended_missing_documents": "Suspend pending required documents",
}


st.set_page_config(
    page_title="Underwriting Copilot",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    html, body, .stApp, .stApp button, .stApp input, .stApp textarea, .stApp table {
        font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    h1, h2, h3, p, label, button, input, textarea { letter-spacing: normal; }
    div[data-testid="stTable"] table { table-layout: fixed; width: 100%; }
    div[data-testid="stTable"] th, div[data-testid="stTable"] td {
        white-space: normal !important;
        overflow-wrap: anywhere;
        word-break: normal;
        vertical-align: top;
        line-height: 1.4;
    }
    div[data-testid="stMetric"] { min-height: 112px; }
    </style>
    """,
    unsafe_allow_html=True,
)


def initialize_session() -> None:
    defaults = {
        "orchestrator": None,
        "workflow_result": None,
        "workflow_config": None,
        "workflow_reference": None,
        "document_paths": [],
        "upload_directory": None,
        "service_error": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def build_session_orchestrator():
    """Build from server-side configuration; reviewers never manage credentials."""
    integrations = build_integrations_from_env(
        GUIDELINES, dotenv_path=PROJECT_ROOT / ".env"
    )
    graph = build_underwriting_orchestrator(
        GUIDELINES,
        document_interpreter=integrations.document_interpreter if integrations else None,
        guideline_store=integrations.guideline_store if integrations else None,
        review_narrator=integrations.review_narrator if integrations else None,
        property_research_service=(
            integrations.property_research_service if integrations else None
        ),
    )
    return graph, integrations


def start_workflow(reference: str, paths: list[Path]) -> None:
    graph, _ = build_session_orchestrator()
    config = {"configurable": {"thread_id": f"streamlit-{uuid.uuid4()}"}}
    result = graph.invoke(
        {
            "loan_id": reference,
            "document_paths": [str(path) for path in paths],
            "workflow_status": "INTAKE",
        },
        config=config,
    )
    st.session_state.orchestrator = graph
    st.session_state.workflow_config = config
    st.session_state.workflow_reference = reference
    st.session_state.document_paths = [str(path) for path in paths]
    st.session_state.workflow_result = result


def resume_workflow(value: dict) -> None:
    st.session_state.workflow_result = st.session_state.orchestrator.invoke(
        Command(resume=value), config=st.session_state.workflow_config
    )


def current_interrupt(result):
    interrupts = result.get("__interrupt__", []) if result else []
    return interrupts[0].value if interrupts else None


def render_intake() -> None:
    st.subheader("Start an underwriting review")
    source = st.radio(
        "Document source",
        ["Realistic sample portfolio", "Upload a PDF package"],
        horizontal=True,
    )
    if source == "Realistic sample portfolio":
        references = available_intake_references(PDF_ROOT)
        reference = st.selectbox(
            "Loan package",
            references,
            format_func=lambda value: f"{value} — {SAMPLE_LABELS.get(value, 'sample package')}",
        )
        paths = resolve_document_paths(PDF_ROOT, reference)
        with st.expander(f"Documents in package ({len(paths)})"):
            for path in paths:
                st.text(path.name)
    else:
        reference = st.text_input("Intake reference", placeholder="e.g. CASE-2026-001").strip()
        uploads = st.file_uploader(
            "Upload mortgage PDFs",
            type=["pdf"],
            accept_multiple_files=True,
            help="Maximum 25 MB per file. Uploads are stored in a temporary session folder.",
        )
        paths = []
        if uploads:
            st.subheader("Uploaded package review")
            total_size = sum(upload.size for upload in uploads)
            left, right = st.columns(2)
            left.metric("Documents uploaded", len(uploads))
            right.metric("Package size", f"{total_size / 1024 / 1024:.2f} MB")
            st.table([
                {
                    "Document": upload.name,
                    "Type": "PDF",
                    "Size": f"{upload.size / 1024:.1f} KB",
                    "Status": "Ready for analysis",
                }
                for upload in uploads
            ])
            for index, upload in enumerate(uploads):
                with st.expander(f"Document {index + 1}: {upload.name}"):
                    st.caption(f"{upload.size / 1024:.1f} KB · PDF document")
                    st.download_button(
                        "Open or download document",
                        data=upload.getvalue(),
                        file_name=upload.name,
                        mime="application/pdf",
                        key=f"uploaded_document_{index}",
                    )

    if st.button("Run underwriting analysis", type="primary", use_container_width=True):
        try:
            if source == "Upload a PDF package":
                if not reference:
                    raise ValueError("Enter an intake reference")
                if not uploads:
                    raise ValueError("Upload at least one PDF")
                upload_dir = Path(tempfile.mkdtemp(prefix="uw_streamlit_"))
                st.session_state.upload_directory = str(upload_dir)
                paths = save_uploaded_pdfs(uploads, upload_dir)
            if not paths:
                raise ValueError("No PDFs were found for this package")
            with st.spinner("Extracting documents and running underwriting agents…"):
                start_workflow(reference, paths)
            st.rerun()
        except Exception as exc:
            st.error(f"Unable to start analysis: {exc}")


def render_missing_documents(payload: dict) -> None:
    st.warning("Additional evidence is required before analysis can continue.")
    missing_types = payload.get("missing_document_types", [])
    missing_evidence = payload.get("missing_evidence", [])
    if missing_types:
        st.write("Missing document categories:", ", ".join(missing_types))
    if missing_evidence:
        st.write("Missing evidence:", ", ".join(missing_evidence))
    uploads = st.file_uploader(
        "Upload requested evidence",
        type=["pdf"],
        accept_multiple_files=True,
        key="resume_documents",
    )
    if st.button("Add documents and resume", type="primary", disabled=not uploads):
        try:
            directory = Path(st.session_state.upload_directory or tempfile.mkdtemp(prefix="uw_resume_"))
            st.session_state.upload_directory = str(directory)
            paths = save_uploaded_pdfs(uploads, directory)
            with st.spinner("Rechecking the document package…"):
                resume_workflow({"document_paths": [str(path) for path in paths]})
            st.rerun()
        except Exception as exc:
            st.error(f"Unable to resume: {exc}")


def render_exception_review(payload: dict) -> None:
    st.warning("Human exception review is required.")
    exceptions = payload.get("exceptions", [])
    for item in exceptions:
        with st.container(border=True):
            st.markdown(f"**{item['code']}** · {item['severity'].title()}")
            st.write(item["details"])
            if item.get("rule_ids"):
                st.caption("Rules: " + ", ".join(item["rule_ids"]))
    with st.form("exception_review_form"):
        reviewer = st.text_input("Reviewer name")
        action = st.radio("Review action", ["acknowledge", "request_changes"], horizontal=True)
        notes = st.text_area("Review notes")
        submitted = st.form_submit_button("Submit review and continue", type="primary")
    if submitted:
        if not reviewer.strip():
            st.error("Reviewer name is required")
        else:
            with st.spinner("Recording review and preparing the final package…"):
                resume_workflow({"action": action, "reviewer": reviewer.strip(), "notes": notes})
            st.rerun()


def render_overview(package) -> None:
    facts = fact_map(package)
    columns = st.columns(4)
    columns[0].metric("Qualifying income", format_money(facts.get("qualifying_monthly_income")))
    columns[1].metric("Verified assets", format_money(facts.get("verified_assets")))
    columns[2].metric("DTI", format_percent(facts.get("dti_percent")))
    columns[3].metric("LTV", format_percent(facts.get("ltv_percent")))
    st.info(package.executive_summary)
    if package.human_review:
        st.subheader("Recorded human review")
        review = package.human_review
        action_label = review.get("action", "unspecified").replace("_", " ").title()
        with st.container(border=True):
            st.markdown(f"**Reviewer action:** {action_label}")
            st.write("Reviewer:", review.get("reviewer", "Unspecified"))
            if review.get("notes"):
                st.write("Notes:", review["notes"])
    st.caption(package.disclaimer)


def render_activity_log(package) -> None:
    st.write(
        "This timeline separates automated analysis from actions explicitly "
        "performed by a human reviewer."
    )
    if not package.observability_log:
        st.info("No workflow activity was recorded.")
        return
    st.table([
        {
            "Time": event.timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
            "Actor": "AI" if event.actor == "ai" else "Human",
            "Phase": event.phase,
            "Action": event.action,
            "Details": event.details,
        }
        for event in package.observability_log
    ])


def render_documents(result: dict) -> None:
    rows = []
    for document in result.get("parsed_documents", []):
        rows.append({
            "File": document.source_path.name,
            "Type": document.document_type.value,
            "Confidence": f"{document.confidence:.0%}",
            "Warnings": "; ".join(document.warnings),
        })
    st.table(rows)


def render_exceptions(package) -> None:
    if not package.exceptions:
        st.success("No normalized exceptions were produced.")
        return
    for item in package.exceptions:
        with st.container(border=True):
            st.markdown(f"**{item.code}** · {item.severity.title()}")
            st.write(item.details)
            if item.rule_ids:
                st.caption("Rules: " + ", ".join(item.rule_ids))
    if package.conditions:
        st.subheader("Conditions")
        for condition in package.conditions:
            st.write("•", condition)


def render_property_research(package) -> None:
    research = package.external_property_research
    if research is None:
        st.info("Property research was not included in this run.")
        return
    st.write("Status:", research.research_status)
    for warning in research.warnings:
        st.warning(warning)
    if research.observations:
        st.table(
            [
                {
                    "Observation": item.observation_type.replace("_", " ").title(),
                    "Amount": format_money(item.amount),
                    "Date": item.event_date or "—",
                    "Confidence": item.corroboration_status.replace("_", " ").title(),
                    "Source": item.source_url,
                }
                for item in research.observations
            ],
        )
    if research.sources:
        st.subheader("Cited sources")
        for source in research.sources:
            with st.container(border=True):
                st.markdown(f"[{source.title}]({source.url})")
                st.caption(f"{source.domain} · source tier {source.source_tier}")
                st.write(source.excerpt)


def render_policy(package) -> None:
    st.subheader("Applicable policy rules")
    if package.applicable_rule_ids:
        st.write(", ".join(package.applicable_rule_ids))
    else:
        st.write("No policy rules were attached.")
    st.subheader("Canonical evidence")
    st.table(
        [
            {
                "Fact": fact.name.replace("_", " ").title(),
                "Value": "—" if fact.value is None else str(fact.value),
                "Source documents": ", ".join(fact.source_document_ids) or "Derived",
            }
            for fact in package.key_facts
        ],
    )


def render_final_result(result: dict) -> None:
    package = result["review_package"]
    st.success("Analysis complete — recommendation ready for qualified human review")
    st.subheader(package.loan_id)
    recommendation = RECOMMENDATION_LABELS.get(
        package.review_disposition,
        package.review_disposition.replace("_", " ").title(),
    )
    st.markdown(f"### Underwriting recommendation: {recommendation}")
    tabs = st.tabs([
        "Overview",
        "Documents",
        "Exceptions",
        "Property research",
        "Policy & evidence",
        "Activity log",
    ])
    with tabs[0]:
        render_overview(package)
    with tabs[1]:
        render_documents(result)
    with tabs[2]:
        render_exceptions(package)
    with tabs[3]:
        render_property_research(package)
    with tabs[4]:
        render_policy(package)
    with tabs[5]:
        render_activity_log(package)


def render_active_workflow() -> None:
    result = st.session_state.workflow_result
    interrupt_payload = current_interrupt(result)
    st.caption(f"Intake reference: {st.session_state.workflow_reference}")
    if interrupt_payload:
        if interrupt_payload.get("type") == "missing_documents":
            render_missing_documents(interrupt_payload)
        elif interrupt_payload.get("type") == "exception_review":
            render_exception_review(interrupt_payload)
        else:
            st.error(f"Unsupported workflow interrupt: {interrupt_payload.get('type')}")
    elif result and "review_package" in result:
        render_final_result(result)
    else:
        st.error("The workflow returned no review package or recognized interrupt.")


initialize_session()

st.title("Underwriting Copilot")
st.write(
    "Evidence-backed mortgage analysis with deterministic calculations, cited policy, "
    "optional property research, and explicit human review checkpoints."
)

if st.session_state.workflow_result is None:
    render_intake()
else:
    if st.sidebar.button("Start a new review", use_container_width=True):
        for key in (
            "orchestrator", "workflow_result", "workflow_config", "workflow_reference",
            "document_paths", "upload_directory", "service_error",
        ):
            st.session_state[key] = None if key not in {"document_paths"} else []
        st.rerun()
    render_active_workflow()
