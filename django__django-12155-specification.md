# django__django-12155: Correct admindoc indentation for first-line summaries

## Scope and provenance

- Repository: `chensx20/django`.
- Required base: `cam-base/django__django-12155-AGYN-S55-20261111T061957Z-36b965`.
- Verified base HEAD: `e8fcdaad5c428878d0a5d6ba820d957013f75595`.
- Research sources: this repository at that commit and the supplied issue description only.
- No external benchmark PR, patch, issue discussion, or web documentation was used.
- This deliverable is a research specification, not an implementation. No production code or tests are changed.

## Problem

A multiline view docstring whose summary starts immediately after the opening quotes has an unindented first physical line and indented continuation lines. Admindoc must remove the common continuation indentation before parsing reStructuredText. Currently it does not.

Reported symptom: Docutils reports that the `default-role` directive permits no content. The repository explains the mechanism, but the Docutils diagnostic was not executed in this environment (see validation status).

## Local implementation and data flow

1. `django/contrib/admindocs/utils.py:27-39`, `trim_docstring()`, returns an empty string for absent/whitespace-only input, expands tabs, splits lines, calculates minimum indentation across every nonblank line, left-strips the first line separately, slices continuation lines by that minimum, right-strips them, and strips the joined result.
2. The calculation at line 37 includes the first line. An immediate summary sets the minimum to zero, retaining source-level indentation on all continuation lines.
3. `utils.py:42-65`, `parse_docstring()`, normalizes the docstring, splits paragraphs into title/body, and parses a final header-like paragraph as metadata.
4. `django/contrib/admindocs/views.py:155-170`, `ViewDetailView.get_context_data()`, parses a view's raw `__doc__`, then renders title and body using the `view` reference context and metadata using the `model` reference context.
5. `utils.py:68-95`, `parse_rst()`, places the supplied text between an initial `.. default-role:: cmsreference` directive and a resetting `.. default-role::` directive. Retained indentation makes a body paragraph look like directive content rather than top-level document text.
6. `django/contrib/admindocs/templates/admin_doc/view_detail.html` displays summary, body, and recognized `Context`/`Templates` metadata. A status-200 response alone does not establish correct rendering.

The same utility is used by tag, filter, and model documentation, so the correction belongs in `trim_docstring()`, not only in the view renderer.

## Required implementation behavior

- Compute common indentation using nonblank continuation lines only; exclude the first physical line regardless of its own indentation.
- If no nonblank continuation line exists, use an indentation of zero. Merely changing the scan to the continuation slice would make `min()` raise on single-line docstrings or a summary followed only by blank lines.
- Preserve existing first-line left trimming, tab expansion before measuring indentation, continuation-line right trimming, final outer stripping, and relative indentation inside structured reST.
- Ignore blank/whitespace-only continuation lines when determining the minimum.
- For genuinely zero-indented continuation text, retain a zero minimum; do not indiscriminately left-strip every line.
- Preserve title/body/metadata separation and metadata values. Do not change parsing contexts or reference URL generation.
- Leave `parse_rst()` directives, global role restoration, disabled raw HTML/file insertion, views, templates, and dependencies unchanged unless a regression test requires a test fixture change.
- Do not replace this small normalization correction with a new parser, compatibility layer, or dependency.

## Reproduction and exact normalization contract

The following text blocks show string content, not implementation code. The input also has a final newline, removed by normalization.

Input (and current normalized content, except its removed final newline):

```text
Summary.

    Body paragraph.

    Context: description
```

Required normalized content:

```text
Summary.

Body paragraph.

Context: description
```
- Required parse result: title `Summary.`, body `Body paragraph.`, metadata mapping with `Context` equal to `description`.
- Rendering the parsed body must produce an ordinary paragraph, not a directive diagnostic or an unintended block quote.

## Regression coverage

### Utility normalization: `tests/admin_docs/test_utils.py`

Use the existing `TestUtils` conventions and explicit expected strings. Keep the leading-newline coverage rather than replacing it.

| Case | Required invariant |
| --- | --- |
| Summary on first physical line; indented body and metadata | Common continuation indent removed; exact normalization and parse result above |
| Multiline summary followed by body | Continuation of summary dedented too; title contains the expected newline |
| Existing leading-newline fixture | Existing normalization, title, body, metadata, links, and definition-list HTML unchanged |
| One-line summary, with and without surrounding whitespace | Summary preserved and outer whitespace removed; no empty-minimum exception |
| Summary followed only by blank/space/tab-only lines | Same result as one-line summary; no exception |
| Absent docstring (`None`), empty string, whitespace-only input | Empty normalized output; parse result remains empty title/body and empty metadata |
| Tabs and mixed indentation | Measure after existing tab expansion; preserve relative nested indentation |
| Nested definition list or literal block | Remove outer continuation indent only; keep nested four-space indentation |
| A continuation line already at column zero | Common continuation indent remains zero; meaningful indentation is not erased |
| First line indented differently from continuation lines | First-line indentation never limits continuation normalization |
| Trailing spaces and CRLF input | Retain current whitespace normalization and newline handling |

Add a focused rendering assertion for parsed first-line-summary input: assert expected paragraph/reference HTML and capture stderr to assert no Docutils diagnostic. Assert absence of rendered `system-message` content as a secondary check, not as the only oracle.

### End-to-end view regression

- Relevant class: `AdminDocViewTests` in `tests/admin_docs/test_views.py:19`; current detail test at lines 72-76 only checks a one-line summary on `BaseAdminDocsView`.
- Add a documented fixture view in `tests/admin_docs/views.py` whose opening line immediately contains the summary, followed by an indented body with structured reST and `Context`/`Templates` metadata.
- Prefer documenting the existing, already-routed `xview` fixture if it does not alter its behavior; otherwise add a small fixture and route in `tests/admin_docs/urls.py`. The callback must be registered because `ViewDetailView._get_view_func()` checks resolver callbacks.
- Request `django-admindocs-views-detail` for that callback using the existing authenticated superuser setup.
- Require HTTP 200, correct summary and body paragraph, preserved nested structure/reference link, expected metadata in context and rendered page, no diagnostic in captured stderr, and no system-message markup.
- Follow existing `captured_stderr` usage in `test_views.py:164-168` and semantic HTML assertions used by the model docstring test at lines 284-301.
- A first-line summary alone does not reproduce the bug. The fixture must include an indented body.

### Existing safeguards that must remain green

`test_trim_docstring`, `test_parse_docstring`, `test_title_output`, `test_description_output`, `test_parse_rst`, and `test_publish_parts` cover nested indentation, metadata, links, default role selection, and restoration of ordinary Docutils interpreted text behavior. Run all `admin_docs` tests to cover model/tag/filter consumers and multiple template engines.

## Dependencies and execution requirements

- This checkout advertises Python 3.6, 3.7, and 3.8 in `setup.cfg:20-22`; use an isolated Python 3.8 environment for this historical source rather than assuming modern Python compatibility.
- Runtime dependencies from `setup.cfg:40-43`: `asgiref >= 3.2`, `pytz`, `sqlparse >= 0.2.2`.
- Install Docutils explicitly. It is optional for Django but required here: `TestUtils` and view test classes are skipped when it is unavailable.
- `tests/requirements/py3.txt` declares broader test dependencies, including unpinned Docutils. Repository content establishes no exact Docutils pin. Record the actual versions used; use a set compatible with the chosen historical interpreter, and do not add speculative dependency constraints to the patch.
- SQLite settings are supplied by `tests/test_sqlite.py`; no external database, browser, JavaScript runner, or web service is required for this change.
- Follow repository `tox.ini` and `docs/internals/contributing/writing-code/unit-tests.txt`. Root-directory commands after activating that environment:

```sh
python -m pip install -e .
python -m pip install docutils
python -m pip freeze
python tests/runtests.py admin_docs.test_utils --settings=test_sqlite --parallel=1
python tests/runtests.py admin_docs.test_views --settings=test_sqlite --parallel=1
python tests/runtests.py admin_docs --settings=test_sqlite --parallel=1
```

The full repository setup is `python -m pip install -r tests/requirements/py3.txt`. With a compatible tox installation, the repository alternative is `tox -e py38 -- admin_docs --settings=test_sqlite --parallel=1`. For an implementation PR, run the configured `flake8` and `isort` environments using tooling compatible with this historical configuration; do not rewrite configuration to satisfy unrelated modern tooling.

## Acceptance and testing gates

- Demonstrate that the new first-line multiline regressions fail against the verified base for the described normalization/rendering reason, not because setup or imports fail.
- Apply the minimal utility correction and demonstrate that those regressions pass.
- All edge cases above pass; single-line summaries and blank continuations do not raise.
- The complete `admin_docs` suite passes with Docutils installed, without relevant skips or Docutils diagnostics.
- Existing reference-role restoration and markup security settings remain unchanged.
- Record interpreter/dependency versions, commands, test counts, failures/skips, and diagnostic output in the implementation PR.

## Validation status of this research

- Branch and exact base HEAD verified; initial working tree was clean.
- Existing utility test command attempted unchanged with local Python 3.12.3 and `PYTHONPATH=.`.
- It failed before test discovery: `ModuleNotFoundError: No module named 'distutils'` from `django/utils/version.py:6`, wrapped by the runner as `RuntimeError: Django module not found, reference tests/README.rst for instructions.` This is an environment failure, not a reproduced test assertion failure.
- `pip`, `docutils`, `asgiref`, `pytz`, and `sqlparse` are absent in the provided runtime. No dependencies were downloaded and no tests can be claimed to pass.
- The rendering symptom and proposed correction are source-based conclusions plus the supplied report; executable reproduction and implementation testing remain required.

## Delivery constraints

Create exactly one documentation-only research PR in `chensx20/django` against the required base branch. Its title must contain both `django__django-12155` and `AGYN-S55-20261111T061957Z-36b965`. Keep it OPEN and never merge it. This document is suitable as the body of one implementation issue; it does not claim the bug has been fixed. No separate GitHub issue is required for this research delivery.
