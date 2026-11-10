# django__django-9296: Paginator iteration implementation specification

## Overview and scope

Research only. No Django implementation, tests, or public documentation are changed
by this research PR. A subsequent implementation should add direct iteration over
Paginator pages, delegating each page number to the existing public page() method.

- Repository: chensx20/django (fork of django/django).
- Required base: swebench-base/django__django-9296.
- Inspected base commit: 84322a29ce9b0940335f8ab3d60e55192bef1e50.
- Research branch: research/django__django-9296-spec.
- Existing task issue (reuse; do not duplicate):
  https://github.com/chensx20/django/issues/106
- Exact upstream implementation PR:
  https://github.com/django/django/pull/9296
- Original upstream ticket, linked and reopened during upstream review:
  https://code.djangoproject.com/ticket/14218

Upstream PR #9296 was merged on October 2, 2019, at 07:49:32 UTC as commit
17595407ca456dc2f0cf3ddb5878ff75615c94ff. That commit is not an ancestor of this
benchmark base. Thus a historically merged upstream feature is genuinely absent
from the supplied branch; do not change the required base or cherry-pick the PR.

## Findings and chosen implementation

In django/core/paginator.py, Paginator has neither __iter__ nor __getitem__;
iter(paginator) therefore raises TypeError. Its page_range property returns
range(1, num_pages + 1), not Page objects. page(number) validates the number,
slices object_list, folds orphans into the final page, and calls _get_page().
Page already inherits collections.abc.Sequence and iterates individual objects.

Add only a generator method named Paginator.__iter__, directly after __init__.
For each page_num in self.page_range, yield self.page(page_num). No other changes
to paginator internals are required. Upstream uses the equivalent local variable
name page_number; the variable name has no behavioral significance.

Alternatives considered: eagerly building a page list loses laziness; looping
through range(1, self.num_pages + 1) bypasses page_range overrides; constructing
Page directly bypasses page() and _get_page() overrides. Delegation through the
existing public methods is the smallest compatible approach.

### Behavioral contract

- Yield Page objects, not page numbers and not flattened source objects.
- Follow the order and values of self.page_range, including subclass overrides.
- Each iterator is independent; each new traversal starts over. Iterators are
  exhausted normally with StopIteration; Paginator is iterable, not an iterator.
- Calling iter(paginator) alone must not count, slice, or create pages. The first
  next() resolves page_range and constructs only the first requested page.
- Keep existing page validation, cached count/num_pages, slicing, orphan handling,
  ordering warnings, and custom _get_page() behavior unchanged.
- Empty source with allow_empty_first_page=True yields one empty Page(number=1).
  With False, it yields nothing; iteration itself must not raise EmptyPage.
  An explicit page(1) in that False case must still raise EmptyPage.
- Exceptions from page_range or page() propagate when the iterator advances.
  Do not use get_page(), catch errors, silently skip pages, or add fallback values.
- Do not add __len__, __getitem__, __next__, a Sequence superclass, page caching,
  special handling of invalid per_page, async iteration, or new dependencies.
- len(paginator), indexing paginator, and next(paginator) remain unsupported.
  Existing Page sequence behavior and paginator.page_range remain unchanged.

### Compatibility and performance

This is additive for valid consumers; code deliberately expecting TypeError from
iter(Paginator) will observe the intended change. Existing subclasses defining
__iter__ retain their override. Inherited iteration must call subclass page(),
page_range, and _get_page() without bypassing them. No database migrations,
settings changes, service integrations, or new request/response schemas apply.

Generator creation is lazy. For an ordered, unevaluated QuerySet, first advancing
the paginator may execute its count query; creating a Page keeps its sliced
QuerySet unevaluated. Consuming that Page fetches that page's rows. Iteration does
not promise streaming SQL, snapshot isolation, or better LIMIT/OFFSET performance.
Explicitly materializing all pages or all contained rows remains caller-driven.

## Precise regression tests

Use tests/pagination/tests.py. Add list-only tests to PaginationTests(SimpleTestCase)
near test_page_range_iterator or at the end of that class. Use self.assertEqual,
self.assertIs, self.assertIsInstance, self.assertRaises, and self.subTest as nearby
tests do. Add Page to the existing paginator import when asserting its type.
Use unittest.mock.patch only where call observation is needed; no new fixtures or
packages. Compare page contents, metadata, and identity of the owning paginator;
do not compare newly constructed Page objects for equality.

1. test_paginator_iteration: Paginator([1, 2, 3], 2); explicitly create iter(p).
   next() yields Page 1 containing [1, 2], then Page 2 containing [3]; both have
   page.paginator is p. Assert Page type, exact number, list(page), and subsequent
   StopIteration. A second traversal yields those same contents in the same order.
2. test_paginator_iteration_empty: Paginator([], 2) yields exactly one empty Page
   numbered 1 owned by p, then StopIteration. Use explicit next(), not merely
   list(p), to distinguish one empty page from no pages.
3. test_paginator_iteration_empty_disallowed: Paginator([], 2,
   allow_empty_first_page=False); first next(iter(p)) raises StopIteration,
   list(p) == [], while p.page(1) still raises EmptyPage.
4. test_paginator_iteration_orphans: Paginator([1, 2, 3, 4, 5], 2, orphans=1)
   yields numbered pages (1, [1, 2]) and (2, [3, 4, 5]), with no third page.
5. test_paginator_iteration_lazy: wrap p.page using patch.object(p, 'page',
   wraps=p.page). Creating iter(p) makes zero calls; first next() calls page(1)
   exactly once; second next() adds only page(2); exhaustion adds no calls.
   Also observe the page_range property with a recording subclass to establish
   that it is not accessed before first next().
6. test_paginator_iteration_custom_page: reuse ValidAdjacentNumsPaginator from
   tests/pagination/custom.py with 'abcdefghijk', per_page=6. Yielded page contents
   are 'abcdef' and 'ghijk'. Assert the custom Page type (import the existing
   ValidAdjacentNumsPage), paginator identity, first.previous_page_number() is None,
   first.next_page_number() == 2, last.previous_page_number() == 1, and
   last.next_page_number() is None. This guards delegation through _get_page().
7. test_paginator_iteration_custom_page_range: a local subclass overrides
   page_range to return (2, 1). With [1, 2, 3], per_page=2, assert page numbers
   [2, 1], contents [[3], [1, 2]], and calls to the overridden page method in
   precisely that order. This prevents bypassing either public extension point.
8. test_paginator_iteration_page_error: a local page override raises a specific
   ValueError instance for page 2. Creating the iterator succeeds; first next()
   yields page 1; second next() raises that identical exception. No suppression,
   conversion to an empty page, or eager raising during iter() is acceptable.
9. test_paginator_iteration_independent_iterators: create two iterators on the
   same three-item/two-per-page paginator. Advance one twice; the other still
   yields page 1 first. A fresh traversal also starts at page 1.

Add test_paginator_iteration to ModelPaginationTests(TestCase) for integration:
reuse its nine Article fixtures and Article.objects.order_by('id'), per_page=5.
Creating iter(p) executes zero queries. Creating the first Page via next() executes
one COUNT query, leaves page.object_list._result_cache as None, and reading its
headlines executes one SELECT for Articles 1 through 5. Creating the second Page
executes zero queries because count/num_pages are cached; reading its headlines
executes one SELECT for Articles 6 through 9. Exhaustion executes zero queries.
Use assertNumQueries around each operation; use list comprehensions over each
Page, not additional values_list() querysets. Assert page numbers and ownership.
Total: three queries for consuming both pages in this controlled fixture.

The essential new iteration tests must fail against the unchanged base with
TypeError at iter(p), then pass after implementation. Existing pagination tests
must continue to pass. Tests should not require new models or a live DB server.

## Public documentation implications

For the eventual implementation (not this research PR):

- docs/ref/paginator.txt: under the Paginator class directive, explain that direct
  iteration yields Page instances. Add an indented versionchanged:: 3.1 directive.
  Update the Page introduction to mention obtaining pages by iterating Paginator.
- Explicitly distinguish Paginator iteration (pages), Page iteration (objects),
  and page_range (1-based integers). State the two empty-input behaviors.
- docs/releases/3.1.txt: add a Pagination subsection under Minor features, with a
  present-tense note that Paginator can now be iterated to yield its pages.
- docs/topics/pagination.txt: optionally add a short nested iteration example.
  Do not rewrite existing navigation or unrelated examples for this task.

Release 3.1 is confirmed by django.VERSION == (3, 1, 0, 'alpha', 0) and the existing
3.1 release-note skeleton. Do not annotate this as 3.0 or use today's release.
The historical upstream diff says len(Paginator) works, but it adds no __len__.
Do not copy that inaccurate sentence or implement __len__ to justify it.
The existing guide also calls the type of page_range a range_iterator although
its implementation and regression test establish range; that pre-existing typo
is not needed for the iterator fix and should not expand its scope.

## Environment and local verification

This historical branch documents CPython 3.6, 3.7, and 3.8 support. Prefer Python
3.8.20 for reproducibility; do not assume current Python works with this old tree.
Use SQLite support in the interpreter. No PostgreSQL, MySQL, Selenium, full test
requirements, JavaScript tooling, or optional database clients are needed here.
The historical runtimes and dependency pins below are for isolated regression
research only, not supported production deployment.

From the repository root, create an isolated environment and install only the
verified focused-suite dependencies. PYTHONPATH selects this checkout, avoiding
editable-build-tool incompatibilities and accidental use of another Django:

```sh
python3.8 -m venv /workspace/django-9296-venv
. /workspace/django-9296-venv/bin/activate
python -m pip install asgiref==3.2.10 pytz==2020.1 sqlparse==0.3.1
export PYTHONPATH=/workspace/django
export PYTHONDONTWRITEBYTECODE=1
python tests/runtests.py pagination.tests.PaginationTests --settings=test_sqlite --parallel=1
python tests/runtests.py pagination.tests.ModelPaginationTests --settings=test_sqlite --parallel=1
python tests/runtests.py pagination --settings=test_sqlite --parallel=1 --verbosity=2
```

For an optional broader generic-view check, after the focused tests pass:

```sh
python tests/runtests.py pagination generic_views --settings=test_sqlite --parallel=1
```

No code changes are needed to reproduce the missing feature: in that environment,
call iter(Paginator([1, 2, 3], 2)); the unchanged base raises TypeError.

### Validation performed

- Unchanged base pagination suite: 20 tests passed on CPython 3.8.20, SQLite,
  asgiref 3.2.10, pytz 2020.1, sqlparse 0.3.1; system checks report no issues.
- Host has no Python interpreter. Docker works, but its remote daemon cannot bind
  mount the client /workspace. Validated by streaming the tracked tree instead:

```sh
git archive HEAD | docker run --rm -i --workdir /workspace/django \
  --env PYTHONDONTWRITEBYTECODE=1 --env PYTHONPATH=/workspace/django \
  python:3.8.20-slim sh -c 'tar -xf - && python -m pip install \
  asgiref==3.2.10 pytz==2020.1 sqlparse==0.3.1 && python tests/runtests.py \
  pagination --settings=test_sqlite --parallel=1 --verbosity=1'
```

The new regression tests above are specifications, not executed tests, because
implementing tests or production code is outside this research-only request.

## Acceptance and handoff

The implementation is complete when the generator delegates exactly through
page_range and page(), the specified regression tests pass along with the existing
pagination suite, and the reference plus 3.1 release note describe only supported
behavior. This research PR must remain documentation-only and must not close the
implementation issue automatically. Use issue #106 as the sole task issue and
one research PR in chensx20/django, targeting the supplied benchmark base.

Additional verification: the documented individual class commands passed (14
PaginationTests and 6 ModelPaginationTests). A standalone read-only probe confirmed
iter(Paginator([1, 2, 3], 2)) raises TypeError with the message "'Paginator' object
is not iterable", while explicit page() access produces [[1, 2], [3]]. Empty-source
page-range policies also match the specified expectations. No proposed new tests
or source changes were applied during these probes.
