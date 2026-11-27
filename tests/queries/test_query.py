from datetime import datetime

from django.core.exceptions import FieldError
from django.db.models import CharField, F, Q
from django.db.models.expressions import Col, SimpleCol
from django.db.models.fields.related_lookups import RelatedIsNull
from django.db.models.functions import Lower
from django.db.models.lookups import Exact, GreaterThan, IsNull, LessThan
from django.db.models.sql.query import Query
from django.db.models.sql.where import OR
from django.test import SimpleTestCase
from django.test.utils import register_lookup

from .models import Author, Item, ObjectC, Ranking


class TestQuery(SimpleTestCase):
    def test_resolve_lookup_value_preserves_list_and_tuple_types(self):
        query = Query(Author)
        for value in ([], (), [1, 2], (1, 2)):
            with self.subTest(value=value):
                resolved = query.resolve_lookup_value(value, None, True, False)
                self.assertEqual(resolved, value)
                self.assertIs(type(resolved), type(value))
                if value:
                    self.assertIsNot(resolved, value)

    def test_resolve_lookup_value_recursively_resolves_expressions(self):
        query = Query(Author)
        value = [F('num'), (2, [F('num'), []]), ()]

        resolved = query.resolve_lookup_value(value, None, True, False)

        self.assertIsInstance(resolved, list)
        self.assertIsInstance(resolved[1], tuple)
        self.assertIsInstance(resolved[1][1], list)
        self.assertIsInstance(resolved[1][1][1], list)
        self.assertIsInstance(resolved[2], tuple)
        self.assertEqual(resolved[1][0], 2)
        self.assertIsInstance(resolved[0], Col)
        self.assertIsInstance(resolved[1][1][0], Col)
        self.assertIsInstance(value[0], F)
        self.assertEqual(value[1][0], 2)
        self.assertIsInstance(value[1][1][0], F)

    def test_resolve_lookup_value_forwards_expression_context_recursively(self):
        query = Query(Author)
        can_reuse = {'existing_alias'}
        calls = []

        class Expression:
            def resolve_expression(self, query, **kwargs):
                calls.append((query, kwargs))
                return 'resolved'

        expression = Expression()

        resolved = query.resolve_lookup_value(
            [1, (expression,)], can_reuse, False, True,
        )

        self.assertEqual(resolved, [1, ('resolved',)])
        self.assertEqual(calls, [(query, {'reuse': can_reuse, 'allow_joins': False})])

    def test_resolve_lookup_value_passes_simple_col_to_f_expressions(self):
        query = Query(Author)

        resolved = query.resolve_lookup_value([[F('num')]], None, True, True)

        self.assertIsInstance(resolved[0][0], SimpleCol)

    def test_resolve_lookup_value_rejects_nested_joins_when_disallowed(self):
        query = Query(Author)
        with self.assertRaises(FieldError):
            query.resolve_lookup_value([[F('extra__info')]], None, False, False)

    def test_simple_query(self):
        query = Query(Author)
        where = query.build_where(Q(num__gt=2))
        lookup = where.children[0]
        self.assertIsInstance(lookup, GreaterThan)
        self.assertEqual(lookup.rhs, 2)
        self.assertEqual(lookup.lhs.target, Author._meta.get_field('num'))

    def test_simplecol_query(self):
        query = Query(Author)
        where = query.build_where(Q(num__gt=2, name__isnull=False) | Q(num__lt=F('id')))

        name_isnull_lookup, num_gt_lookup = where.children[0].children
        self.assertIsInstance(num_gt_lookup, GreaterThan)
        self.assertIsInstance(num_gt_lookup.lhs, SimpleCol)
        self.assertIsInstance(name_isnull_lookup, IsNull)
        self.assertIsInstance(name_isnull_lookup.lhs, SimpleCol)

        num_lt_lookup = where.children[1]
        self.assertIsInstance(num_lt_lookup, LessThan)
        self.assertIsInstance(num_lt_lookup.rhs, SimpleCol)
        self.assertIsInstance(num_lt_lookup.lhs, SimpleCol)

    def test_complex_query(self):
        query = Query(Author)
        where = query.build_where(Q(num__gt=2) | Q(num__lt=0))
        self.assertEqual(where.connector, OR)

        lookup = where.children[0]
        self.assertIsInstance(lookup, GreaterThan)
        self.assertEqual(lookup.rhs, 2)
        self.assertEqual(lookup.lhs.target, Author._meta.get_field('num'))

        lookup = where.children[1]
        self.assertIsInstance(lookup, LessThan)
        self.assertEqual(lookup.rhs, 0)
        self.assertEqual(lookup.lhs.target, Author._meta.get_field('num'))

    def test_multiple_fields(self):
        query = Query(Item)
        where = query.build_where(Q(modified__gt=F('created')))
        lookup = where.children[0]
        self.assertIsInstance(lookup, GreaterThan)
        self.assertIsInstance(lookup.rhs, SimpleCol)
        self.assertIsInstance(lookup.lhs, SimpleCol)
        self.assertEqual(lookup.rhs.target, Item._meta.get_field('created'))
        self.assertEqual(lookup.lhs.target, Item._meta.get_field('modified'))

    def test_transform(self):
        query = Query(Author)
        with register_lookup(CharField, Lower):
            where = query.build_where(~Q(name__lower='foo'))
        lookup = where.children[0]
        self.assertIsInstance(lookup, Exact)
        self.assertIsInstance(lookup.lhs, Lower)
        self.assertIsInstance(lookup.lhs.lhs, SimpleCol)
        self.assertEqual(lookup.lhs.lhs.target, Author._meta.get_field('name'))

    def test_negated_nullable(self):
        query = Query(Item)
        where = query.build_where(~Q(modified__lt=datetime(2017, 1, 1)))
        self.assertTrue(where.negated)
        lookup = where.children[0]
        self.assertIsInstance(lookup, LessThan)
        self.assertEqual(lookup.lhs.target, Item._meta.get_field('modified'))
        lookup = where.children[1]
        self.assertIsInstance(lookup, IsNull)
        self.assertEqual(lookup.lhs.target, Item._meta.get_field('modified'))

    def test_foreign_key(self):
        query = Query(Item)
        msg = 'Joined field references are not permitted in this query'
        with self.assertRaisesMessage(FieldError, msg):
            query.build_where(Q(creator__num__gt=2))

    def test_foreign_key_f(self):
        query = Query(Ranking)
        with self.assertRaises(FieldError):
            query.build_where(Q(rank__gt=F('author__num')))

    def test_foreign_key_exclusive(self):
        query = Query(ObjectC)
        where = query.build_where(Q(objecta=None) | Q(objectb=None))
        a_isnull = where.children[0]
        self.assertIsInstance(a_isnull, RelatedIsNull)
        self.assertIsInstance(a_isnull.lhs, SimpleCol)
        self.assertEqual(a_isnull.lhs.target, ObjectC._meta.get_field('objecta'))
        b_isnull = where.children[1]
        self.assertIsInstance(b_isnull, RelatedIsNull)
        self.assertIsInstance(b_isnull.lhs, SimpleCol)
        self.assertEqual(b_isnull.lhs.target, ObjectC._meta.get_field('objectb'))

    def test_clone_select_related(self):
        query = Query(Item)
        query.add_select_related(['creator'])
        clone = query.clone()
        clone.add_select_related(['note', 'creator__extra'])
        self.assertEqual(query.select_related, {'creator': {}})
