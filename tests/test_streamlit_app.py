from pathlib import Path

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


def test_default_sample_reaches_human_exception_review(monkeypatch):
    monkeypatch.setenv("USE_OPENAI_DOCUMENT_MODEL", "false")
    monkeypatch.setenv("USE_OPENAI_REVIEW_NARRATOR", "false")
    monkeypatch.setenv("USE_PROPERTY_WEB_RESEARCH", "false")
    monkeypatch.setenv("GUIDELINE_VECTOR_BACKEND", "local")
    app = AppTest.from_file(str(ROOT / "streamlit_app.py")).run(timeout=30)
    assert not app.exception
    assert not any("env" in toggle.label.casefold() for toggle in app.toggle)

    next(
        button for button in app.button
        if button.label == "Run underwriting analysis"
    ).click().run(timeout=30)

    assert not app.exception
    assert any(
        "Human exception review is required" in warning.value
        for warning in app.warning
    )
    assert any(widget.label == "Reviewer name" for widget in app.text_input)
    assert any(
        button.label == "Submit review and continue" for button in app.button
    )

    next(widget for widget in app.text_input if widget.label == "Reviewer name").set_value(
        "Test Reviewer"
    )
    next(
        button for button in app.button
        if button.label == "Submit review and continue"
    ).click().run(timeout=30)

    assert not app.exception
    assert any(
        "Underwriting recommendation" in item.value for item in app.markdown
    )
    assert [tab.label for tab in app.tabs] == [
        "Overview",
        "Documents",
        "Exceptions",
        "Property research",
        "Policy & evidence",
        "Activity log",
    ]
    assert any("Recorded human review" in item.value for item in app.subheader)
