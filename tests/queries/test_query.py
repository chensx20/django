from datetime import datetime
from unittest import mock

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
    def test_resolve_lookup_value_iterables(self):
        query = Query(Author)
        for value in ([], (), [1, None, 'name'], (1, None, 'name')):
            with self.subTest(value=value):
                resolved = query.resolve_lookup_value(value, set(), True, False)
                self.assertIs(type(resolved), type(value))
                self.assertEqual(resolved, value)

    def test_resolve_lookup_value_nested_iterables(self):
        query = Query(Author)
        for container in (list, tuple):
            value = container([1, [2, (3, [], ())], (4, [5])])
            resolved = query.resolve_lookup_value(value, set(), True, False)
            with self.subTest(container=container):
                self.assertIs(type(resolved), container)
                self.assertEqual(resolved, value)
                self.assertIsNot(resolved[1], value[1])
                self.assertIsNot(resolved[2][1], value[2][1])
                self.assertEqual(value, container([1, [2, (3, [], ())], (4, [5])]))

    def test_resolve_lookup_value_expressions(self):
        query = Query(Author)
        for container in (list, tuple):
            for nested in (False, True):
                for simple_col in (False, True):
                    field = F('num')
                    expression = Lower('name')
                    children = [field, expression, None, 7]
                    value = container([(children,)] if nested else children)
                    resolved = query.resolve_lookup_value(value, set(), True, simple_col)
                    with self.subTest(container=container, nested=nested, simple_col=simple_col):
                        self.assertIs(type(resolved), container)
                        if nested:
                            self.assertIsInstance(resolved[0], tuple)
                            self.assertIsInstance(resolved[0][0], list)
                            self.assertIsNot(resolved[0][0], children)
                            resolved = resolved[0][0]
                        self.assertIsInstance(resolved[0], SimpleCol if simple_col else Col)
                        self.assertEqual(resolved[0].target, Author._meta.get_field('num'))
                        self.assertIsInstance(resolved[1], Lower)
                        self.assertIsInstance(resolved[1].lhs, Col)
                        self.assertEqual(resolved[1].lhs.target, Author._meta.get_field('name'))
                        self.assertEqual(list(resolved[2:]), [None, 7])
                        self.assertEqual(value, container([(children,)] if nested else children))
                        self.assertIs(children[0], field)
                        self.assertIs(children[1], expression)
                        self.assertEqual(expression.get_source_expressions(), [F('name')])

    def test_resolve_lookup_value_expression_context(self):
        query = Query(Author)
        for can_reuse in (None, set(), {'alias'}):
            for allow_joins in (False, True):
                for simple_col in (False, True):
                    for depth in range(3):
                        for expression in (F('num'), Lower('name')):
                            value = expression
                            for container in (list, tuple)[:depth]:
                                value = container([value])
                            with self.subTest(
                                can_reuse=can_reuse, allow_joins=allow_joins,
                                simple_col=simple_col, depth=depth, expression=expression,
                            ):
                                with mock.patch.object(
                                    expression, 'resolve_expression', wraps=expression.resolve_expression,
                                ) as resolve_expression:
                                    query.resolve_lookup_value(value, can_reuse, allow_joins, simple_col)
                                kwargs = {'reuse': can_reuse, 'allow_joins': allow_joins}
                                if isinstance(expression, F):
                                    kwargs['simple_col'] = simple_col
                                resolve_expression.assert_called_once_with(query, **kwargs)
                                self.assertIs(resolve_expression.call_args[1]['reuse'], can_reuse)

    def test_resolve_lookup_value_nested_join_not_allowed(self):
        query = Query(Ranking)
        msg = 'Joined field references are not permitted in this query'
        with self.assertRaisesMessage(FieldError, msg):
            query.resolve_lookup_value([(F('author__num'),)], set(), False, False)

    def test_resolve_lookup_value_other_iterables(self):
        query = Query(Author)
        expression = F('num')
        values = ({'field': expression}, {expression}, iter([expression]))
        for value in values:
            with self.subTest(value=value):
                self.assertIs(query.resolve_lookup_value(value, set(), True, False), value)

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
