# django__django-12276: FileInput required attribute with initial files

## Scope and provenance

Research only: no implementation or test code is changed by this document.
Sources are exclusively the supplied issue description and this repository at
53d8646f799de7f92ab9defe9dc56c6125448102, on base branch
`cam-base/django__django-12276-AGYN-S55-20261111T070910Z-77ccad`.
No previous benchmark patches, PRs, issue discussions, or external research
were consulted. The supplied checkout was absent; it was cloned from the
specified repository and its branch and HEAD were verified exactly.

## Current behavior and cause

- Inheritance is Widget -> Input -> FileInput -> ClearableFileInput.
  Widget.use_required_attribute() returns whether the widget is not hidden
  (django/forms/widgets.py:275). Input does not override the hook.
- FileInput (django/forms/widgets.py:374-389) has no override. Consequently,
  its visible input remains eligible for the automatic required attribute,
  including when there is an existing initial file.
- ClearableFileInput alone overrides the hook at widgets.py:454-455: it
  combines the superclass result with the absence of a truthy initial value.
- BoundField.build_widget_attrs() (django/forms/boundfield.py:221-228) adds
  required only when the hook, field.required, and form.use_required_attribute
  all permit it. The hook receives BoundField.initial, not the uploaded value.
- BaseModelForm.__init__() populates initial data from model_to_dict(instance)
  (django/forms/models.py:276-303). Thus an edit form using a plain FileInput
  receives its existing file as initial data but still renders required today.
- FileInput.format_value() never renders a value attribute. A browser cannot
  use the existing initial file to satisfy an empty, required upload control.
- Server-side behavior already permits retention: FileField.clean() returns
  the initial value when no new upload exists and initial is truthy
  (django/forms/fields.py:579-596). The bug is automatic HTML validation,
  not the server-side required-field policy.
- FileField defaults to ClearableFileInput (fields.py:540-541), so the affected
  case requires choosing FileInput or a subclass that inherits its hook.
  AdminFileWidget inherits ClearableFileInput (django/contrib/admin/widgets.py:101)
  and must retain its existing behavior.

## Implementation specification

1. Move the existing use_required_attribute(initial) override, with its exact
   superclass-and-initial semantics, from ClearableFileInput into FileInput
   in django/forms/widgets.py. Remove the redundant subclass definition.
   Preserve the superclass call so hidden-widget behavior remains intact.
2. Do not change rendering templates, format_value(), upload extraction,
   multipart handling, clear-checkbox handling, FileField.clean(), model
   persistence, or BoundField.build_widget_attrs(). No new dependency is needed.
3. Add direct regression coverage in
   tests/forms_tests/widget_tests/test_fileinput.py, using the local WidgetTest
   conventions. Assert True for None and an empty string, and False for a
   nonempty filename. Cover the inherited hidden-widget guard as well.
4. Retain tests/forms_tests/widget_tests/test_clearablefileinput.py's existing
   test_use_required_attribute assertions as regression protection for inherited
   behavior; do not remove this coverage merely because the method moved.
5. Extend form-level coverage in tests/forms_tests/tests/test_forms.py near
   FormsTestCase.test_forms_with_file_fields. Exercise FileField explicitly
   configured with FileInput, not only the default ClearableFileInput.
   Cover unbound initial rendering, bound retention with no upload, and the
   no-initial required case. Assert real rendered HTML and cleaned values.
6. Add a targeted ModelForm regression in tests/model_forms/tests.py near
   FileAndImageFieldTests, reusing TextFile and configuring its file widget as
   FileInput. TextFile.file is required (tests/model_forms/models.py:127-129).
   Supply a valid description when binding the form. Use an instance with an
   existing file name to test instance-derived initial data, retain that file
   when no upload is submitted, and verify the rendered file input lacks the
   automatic required attribute. No actual storage write is needed to establish
   the widget/validation regression. Document.myfile is blank=True and would
   not establish the required-field regression.
7. Update docs/ref/forms/widgets.txt:318-335, the Widget.use_required_attribute
   reference, to name both FileInput and ClearableFileInput as suppressing the
   automatic required attribute when initial is set. Clarify that this means
   truthy initial data. Add a versionchanged:: 3.1 note identifying the change
   for FileInput. A release-note entry in docs/releases/3.1.txt's Forms section
   is optional editorial follow-up, not a prerequisite for this small fix.

## Acceptance criteria

- Visible FileInput: hook returns True for None or an empty string, and False
  for a nonempty filename or truthy existing FieldFile.
- A hidden FileInput subclass remains ineligible for required regardless of
  whether initial data is absent or present.
- ClearableFileInput satisfies the same matrix through inheritance; its
  current-file display, optional clearing, and contradiction handling remain
  unchanged. Existing clearable and admin regression coverage still passes.
- A required plain-file form without initial data renders required and rejects
  an empty submission with the existing required validation error.
- A required plain-file form with truthy initial data renders no automatically
  generated required attribute on unbound rendering and bound redisplay; an
  empty upload submission validates and retains exactly the initial file.
- An edit ModelForm using FileInput obtains its existing file from the instance,
  omits automatic required, and retains it without re-upload. A corresponding
  instance with no file remains subject to required validation.
- A replacement upload remains accepted and replaces the cleaned value rather
  than forcing retention of the initial value.
- required=False and form.use_required_attribute=False still suppress automatic
  required. File inputs still never render a value attribute.
- The source contains one implementation of this file-specific rule, on
  FileInput, and no redundant ClearableFileInput override.
- Focused tests and broader forms/model-form regression suites pass in a
  provisioned supported environment; the reference documentation matches the
  expanded behavior. The new plain-FileInput regression fails on this baseline
  and passes after the future implementation.

## Existing coverage and gaps

- tests/forms_tests/widget_tests/test_fileinput.py: FileInputTest currently
  covers value-free rendering and omission from files, but not this hook.
- tests/forms_tests/widget_tests/test_clearablefileinput.py:153-157 already
  covers None and a nonempty initial filename for ClearableFileInput.
- tests/forms_tests/tests/test_forms.py:2421-2479 already checks required file
  rendering and initial filenames, but uses FileField's default clearable widget.
- tests/forms_tests/field_tests/test_filefield.py:44-50 already verifies initial
  filename retention through clean(); preserve this behavior.
- tests/model_forms/tests.py:1927 onward exercises clearing, contradictions, and
  file persistence, but does not establish the required plain-FileInput case.
- WidgetTest optionally runs rendering assertions against Jinja2 when installed
  (tests/forms_tests/widget_tests/base.py); retain that convention.

## Environment, setup, and verification

The checkout reports Django 3.1 alpha. setup.cfg and docs/releases/3.1.txt
identify Python 3.6, 3.7, and 3.8 as its supported versions. Available local
interpreters include Python 3.12.3 and /usr/local/bin/python3.7 (3.7.16).

Attempted, from the repository root, with PYTHONDONTWRITEBYTECODE=1 and
PYTHONPATH=/workspace/django:

- Python 3.12: tests/runtests.py with the two widget modules and --parallel=1
  fails before collection: ModuleNotFoundError: No module named 'distutils'.
  The runner's outer 'Django module not found' error wraps that original failure;
  it is not evidence that PYTHONPATH was incorrect.
- Python 3.7: the same command fails before collection:
  ModuleNotFoundError: No module named 'asgiref'.

No tests ran or passed. No dependencies were downloaded, no compatibility
shims were added, and no source files were modified to work around these errors.
Do not use Python 3.12 for validating this historical branch.

Use a provisioned Python 3.6-3.8 virtual environment. Repository instructions
are in tests/README.rst, tox.ini, setup.cfg, and
docs/internals/contributing/writing-code/unit-tests.txt. They prescribe an
editable install and tests/requirements/py3.txt. Those requirements are mostly
unbounded; installing them today can select versions incompatible with this
historical interpreter or framework. Provision compatible dependencies explicitly
rather than modifying the application to accommodate modern versions. Exact
working dependency pins were not established in this research.

Setup commands from the root (not executed here):

    python -m pip install -e .
    python -m pip install -r tests/requirements/py3.txt

Focused verification from the root, using that environment's python:

    PYTHONPATH=. python tests/runtests.py forms_tests.widget_tests.test_fileinput forms_tests.widget_tests.test_clearablefileinput --settings=test_sqlite --parallel=1
    PYTHONPATH=. python tests/runtests.py forms_tests.tests.test_forms.FormsTestCase.test_forms_with_file_fields forms_tests.field_tests.test_filefield model_forms.tests.FileAndImageFieldTests --settings=test_sqlite --parallel=1

Include the new form/model test labels in the focused run after naming them.
Broader regression command:

    PYTHONPATH=. python tests/runtests.py forms_tests model_forms admin_widgets --settings=test_sqlite --parallel=1

Equivalent repository-supported tox entry point:

    tox -e py37 -- forms_tests model_forms admin_widgets --parallel=1

Model-form tests need the SQLite test database; some image coverage requires
Pillow. Jinja2 is optional additional rendering coverage. Start with the focused
widget modules before provisioning the full suite's optional dependencies.

## Caveats and non-goals

- 'Initial exists' follows truthiness, not a storage existence check or a URL
  check. Do not replace the rule with ClearableFileInput.is_initial(), which
  requires a URL for display and would change semantics for initial filenames.
- A bound upload alone is not initial data. With no initial file, required can
  still appear on bound redisplay; browsers do not repopulate upload controls.
- The hook controls automatic attributes only. Explicit required attributes in
  widget attrs, as_widget attrs, or custom templates are not removed by this
  change. Direct widget.render() does not itself invoke BoundField's hook.
- Initial values remain trusted server-side form configuration; do not treat
  submitted filenames as initial files or loosen server-side required checks.
- Subclasses inheriting FileInput gain the correction. A custom override that
  never calls super() remains responsible for its own behavior; custom overrides
  that do call super() will observe the corrected superclass policy.
- No new clearing feature, file-value prepopulation, storage I/O, migration,
  API integration, dependency upgrade, or unrelated widget behavior is in scope.
- This PR is a research deliverable only. Implementation acceptance criteria
  intentionally remain unfulfilled until a separate authorized implementation.
