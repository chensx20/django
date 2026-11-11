import copy
import pickle
import uuid
from unittest import mock

from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import DEFERRED, signals
from django.test import TestCase

from .models import (
    ConcreteDefaultPK, DefaultPKChild, DefaultPKGrandchild, DefaultPKProxy,
    WithCustomPK, WithDefaultPK, WithFalsyDefaultPK,
)


class DefaultPrimaryKeyTests(TestCase):
    def test_generated_default(self):
        field = WithDefaultPK._meta.pk
        with mock.patch.object(field, 'get_default', wraps=field.get_default) as default:
            with self.assertNumQueries(1) as queries:
                obj = WithDefaultPK(value=1)
                obj.save()
            default.assert_called_once_with()
        self.assertTrue(queries[0]['sql'].startswith('INSERT'))
        obj.value = 2
        with self.assertNumQueries(1):
            obj.save()
        self.assertEqual(WithDefaultPK.objects.get().value, 2)

    def test_supplied_constructor_keys(self):
        for constructor in (
            lambda pk: WithDefaultPK(pk=pk, value=2),
            lambda pk: WithDefaultPK(key=pk, value=2),
            lambda pk: WithDefaultPK(pk, 2),
        ):
            for existing in (False, True):
                with self.subTest(constructor=constructor, existing=existing):
                    pk = uuid.uuid4()
                    if existing:
                        WithDefaultPK.objects.create(pk=pk, value=1)
                    obj = constructor(pk)
                    with self.assertNumQueries(1 if existing else 2) as queries:
                        obj.save()
                    self.assertTrue(queries[0]['sql'].startswith('UPDATE'))
                    self.assertEqual(WithDefaultPK.objects.get(pk=pk).value, 2)

    def test_assigned_keys(self):
        for attribute in ('pk', 'key'):
            for existing in (False, True):
                with self.subTest(attribute=attribute, existing=existing):
                    obj = WithDefaultPK(value=2)
                    pk = uuid.uuid4()
                    if existing:
                        WithDefaultPK.objects.create(pk=pk, value=1)
                    setattr(obj, attribute, pk)
                    with self.assertNumQueries(1 if existing else 2) as queries:
                        obj.save()
                    self.assertTrue(queries[0]['sql'].startswith('UPDATE'))
                    self.assertEqual(WithDefaultPK.objects.get(pk=pk).value, 2)

    def test_same_value_assignment(self):
        for attribute in ('pk', 'key'):
            with self.subTest(attribute=attribute):
                obj = WithDefaultPK(value=2)
                WithDefaultPK.objects.create(pk=obj.pk, value=1)
                setattr(obj, attribute, obj.pk)
                with self.assertNumQueries(1):
                    obj.save()
                self.assertEqual(WithDefaultPK.objects.get(pk=obj.pk).value, 2)

    def test_generated_collision_is_not_an_update(self):
        obj = WithDefaultPK(value=2)
        WithDefaultPK.objects.create(pk=obj.pk, value=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            obj.save()
        self.assertEqual(WithDefaultPK.objects.get(pk=obj.pk).value, 1)

    def test_save_time_generation(self):
        obj = WithDefaultPK(pk=None)
        field = WithDefaultPK._meta.pk
        with mock.patch.object(field, 'get_default', wraps=field.get_default) as default:
            with self.assertNumQueries(1):
                obj.save()
            default.assert_called_once_with()
        self.assertIsNotNone(obj.pk)

    def test_signal_assignment(self):
        for signal in (signals.post_init, signals.pre_save):
            for same_value in (False, True):
                with self.subTest(signal=signal, same_value=same_value):
                    pk = uuid.uuid4()
                    WithDefaultPK.objects.create(pk=pk, value=1)

                    def assign(sender, instance, **kwargs):
                        instance.pk = instance.pk if same_value else pk

                    signal.connect(assign, sender=WithDefaultPK)
                    try:
                        if same_value:
                            with mock.patch.object(WithDefaultPK._meta.pk, 'get_default', return_value=pk):
                                obj = WithDefaultPK(value=2)
                        else:
                            obj = WithDefaultPK(value=2)
                        with self.assertNumQueries(1):
                            obj.save()
                    finally:
                        signal.disconnect(assign, sender=WithDefaultPK)
                    self.assertEqual(WithDefaultPK.objects.get(pk=pk).value, 2)

    def test_update_only(self):
        for options in ({'force_update': True}, {'update_fields': {'value'}}):
            for generated in (False, True):
                for existing in (False, True):
                    with self.subTest(options=options, generated=generated, existing=existing):
                        obj = WithDefaultPK(value=2) if generated else WithDefaultPK(pk=uuid.uuid4(), value=2)
                        if existing:
                            WithDefaultPK.objects.create(pk=obj.pk, value=1)
                            with self.assertNumQueries(1):
                                obj.save(**options)
                            self.assertEqual(WithDefaultPK.objects.get(pk=obj.pk).value, 2)
                        else:
                            msg = (
                                'Forced update did not affect any rows.' if 'force_update' in options else
                                'Save with update_fields did not affect any rows.'
                            )
                            with self.assertRaisesMessage(DatabaseError, msg), transaction.atomic():
                                obj.save(**options)
                            self.assertFalse(WithDefaultPK.objects.filter(pk=obj.pk).exists())

    def test_force_insert(self):
        obj = WithDefaultPK.objects.create()
        with self.assertRaises(IntegrityError), transaction.atomic():
            WithDefaultPK(pk=obj.pk).save(force_insert=True)
        with self.assertNumQueries(1):
            WithDefaultPK(pk=uuid.uuid4()).save(force_insert=True)

    def test_conflicting_flags(self):
        obj = WithDefaultPK()
        for options in ({'force_update': True}, {'update_fields': {'value'}}):
            with self.assertRaisesMessage(ValueError, 'Cannot force both insert and updating in model saving.'):
                obj.save(force_insert=True, **options)

    def test_empty_update_fields(self):
        obj = WithDefaultPK()
        with self.assertNumQueries(0):
            obj.save(update_fields=[])
        self.assertTrue(obj._state.adding)
        with self.assertNumQueries(1):
            obj.save()

    def test_raw_save(self):
        for existing in (False, True):
            obj = WithDefaultPK(value=2)
            if existing:
                WithDefaultPK.objects.create(pk=obj.pk, value=1)
            with mock.patch.object(WithDefaultPK._meta.get_field('value'), 'pre_save') as pre_save:
                with self.assertNumQueries(1 if existing else 2) as queries:
                    obj.save_base(raw=True)
                pre_save.assert_not_called()
            self.assertTrue(queries[0]['sql'].startswith('UPDATE'))
            self.assertEqual(WithDefaultPK.objects.get(pk=obj.pk).value, 2)

    def test_loaded_deferred_and_refreshed_keys(self):
        original = WithDefaultPK.objects.create(value=1)
        for obj in (WithDefaultPK.objects.get(pk=original.pk), WithDefaultPK.objects.only('key').get()):
            self.assertNotIn('key', obj._generated_pk_fields)
            obj.value = 2
            with self.assertNumQueries(1):
                obj.save()
        obj = WithDefaultPK(key=DEFERRED, value=3)
        self.assertNotIn('key', obj._generated_pk_fields)
        obj.key = original.pk
        obj.refresh_from_db()
        self.assertEqual(obj.value, 2)
        with self.assertNumQueries(1):
            obj.save()

    def test_refresh_generated_key(self):
        obj = WithDefaultPK()
        WithDefaultPK.objects.create(pk=obj.pk, value=1)
        obj.refresh_from_db()
        with self.assertNumQueries(1):
            obj.save()

    def test_deleted_key_is_deferred(self):
        obj = DefaultPKChild.objects.create(value=1)
        del obj.key
        with self.assertNumQueries(0):
            self.assertIsNotNone(obj.key)
        self.assertNotIn('key', obj._generated_pk_fields)

    def test_copy_and_pickle_isolation(self):
        for clone in (copy.copy, copy.deepcopy, lambda obj: pickle.loads(pickle.dumps(obj))):
            with self.subTest(clone=clone):
                obj = WithDefaultPK()
                copied = clone(obj)
                copied.pk = copied.pk
                self.assertIn('key', obj._generated_pk_fields)
                self.assertNotIn('key', copied._generated_pk_fields)
                with self.assertNumQueries(1):
                    obj.save()
                copied.value = 2
                with self.assertNumQueries(1):
                    copied.save()
                self.assertEqual(WithDefaultPK.objects.get(pk=obj.pk).value, 2)

    def test_no_default(self):
        for existing in (False, True):
            pk = 10 if existing else 20
            if existing:
                WithCustomPK.objects.create(pk=pk, value=1)
            with self.assertNumQueries(1 if existing else 2):
                WithCustomPK(pk=pk, value=2).save()

    def test_falsy_default_eligibility(self):
        with self.assertNumQueries(2) as queries:
            WithFalsyDefaultPK(value=1).save()
        self.assertTrue(queries[0]['sql'].startswith('UPDATE'))
        with self.assertNumQueries(1):
            WithFalsyDefaultPK(value=2).save()
        self.assertEqual(WithFalsyDefaultPK.objects.get().value, 2)

    def test_callable_default_returning_falsy_value(self):
        field = WithFalsyDefaultPK._meta.pk
        with mock.patch.object(field, 'default', lambda: 0):
            with self.assertNumQueries(1) as queries:
                WithFalsyDefaultPK().save()
        self.assertTrue(queries[0]['sql'].startswith('INSERT'))

    def test_proxy_and_abstract_defaults(self):
        for model in (DefaultPKProxy, ConcreteDefaultPK):
            with self.subTest(model=model):
                with self.assertNumQueries(1):
                    obj = model.objects.create()
                with self.assertNumQueries(1):
                    model(pk=obj.pk, value=2).save()


class InheritedDefaultPrimaryKeyTests(TestCase):
    def test_generated_default_per_table(self):
        for model, count in ((DefaultPKChild, 2), (DefaultPKGrandchild, 3)):
            with self.subTest(model=model):
                with self.assertNumQueries(count) as queries:
                    obj = model(value=1)
                    obj.save()
                self.assertTrue(all(query['sql'].startswith('INSERT') for query in queries))
                self.assertEqual(model.objects.get(pk=obj.pk).key, obj.pk)

    def test_supplied_parent_identities(self):
        for model in (DefaultPKChild, DefaultPKGrandchild):
            for attribute in ('pk', 'key', 'withdefaultpk_ptr_id'):
                with self.subTest(model=model, attribute=attribute):
                    parent = WithDefaultPK.objects.create(value=1)
                    obj = model(**{attribute: parent.pk, 'value': 2})
                    obj.save()
                    self.assertEqual(obj.pk, parent.pk)
                    parent.refresh_from_db()
                    self.assertEqual(parent.value, 2)

    def test_existing_children(self):
        for model in (DefaultPKChild, DefaultPKGrandchild):
            original = model.objects.create(value=1)
            obj = model(pk=original.pk, value=2)
            obj.save()
            self.assertEqual(model.objects.get(pk=original.pk).value, 2)

    def test_assigned_parent_identities(self):
        for model in (DefaultPKChild, DefaultPKGrandchild):
            for attribute in ('pk', 'key', 'withdefaultpk_ptr_id'):
                for same_value in (False, True):
                    with self.subTest(model=model, attribute=attribute, same_value=same_value):
                        obj = model(value=2)
                        pk = obj.key if same_value else uuid.uuid4()
                        parent = WithDefaultPK.objects.create(pk=pk, value=1)
                        setattr(obj, attribute, pk)
                        obj.save()
                        self.assertEqual(obj.pk, parent.pk)
                        parent.refresh_from_db()
                        self.assertEqual(parent.value, 2)

    def test_intermediate_link_precedence(self):
        first = DefaultPKChild.objects.create()
        second = DefaultPKChild.objects.create()
        obj = DefaultPKGrandchild(withdefaultpk_ptr_id=first.pk, pk=second.pk, value=2)
        obj.save()
        self.assertEqual(obj.pk, first.pk)
        second.refresh_from_db()
        self.assertEqual(second.value, 0)

    def test_deferred_child(self):
        original = DefaultPKGrandchild.objects.create(value=1)
        obj = DefaultPKGrandchild.objects.only('grandchild_value').get(pk=original.pk)
        with self.assertNumQueries(0):
            self.assertEqual(obj.key, original.pk)
        self.assertNotIn('key', obj._generated_pk_fields)
        obj.value = 2
        obj.save()
        original.refresh_from_db()
        self.assertEqual(original.value, 2)

    def test_update_only_existing_ancestors(self):
        for options in ({'force_update': True}, {'update_fields': {'value'}}):
            original = DefaultPKGrandchild.objects.create(value=1)
            obj = DefaultPKGrandchild(pk=original.pk, value=2)
            obj.save(**options)
            original.refresh_from_db()
            self.assertEqual(original.value, 2)

    def test_parent_object_and_cache(self):
        parent = WithDefaultPK.objects.create(value=1)
        obj = DefaultPKChild(withdefaultpk_ptr=parent, value=2)
        self.assertIs(obj.withdefaultpk_ptr, parent)
        obj.save()
        self.assertEqual(obj.pk, parent.pk)
        self.assertEqual(obj.withdefaultpk_ptr.value, 2)
        other = WithDefaultPK.objects.create(value=3)
        obj.withdefaultpk_ptr_id = other.pk
        self.assertFalse(DefaultPKChild._meta.pk.is_cached(obj))

    def test_conflicting_explicit_ancestor_takes_precedence(self):
        first = WithDefaultPK.objects.create()
        second = WithDefaultPK.objects.create()
        obj = DefaultPKGrandchild(key=first.pk, pk=second.pk, value=2)
        obj.save()
        self.assertEqual(obj.pk, first.pk)
        second.refresh_from_db()
        self.assertEqual(second.value, 0)

    def test_update_only_cannot_insert_ancestor(self):
        for model in (DefaultPKChild, DefaultPKGrandchild):
            for options in ({'force_update': True}, {'update_fields': {'value'}}):
                with self.subTest(model=model, options=options):
                    obj = model(value=1)
                    with self.assertRaises(DatabaseError), transaction.atomic():
                        obj.save(**options)
                    self.assertFalse(WithDefaultPK.objects.filter(pk=obj.key).exists())

    def test_raw_bypasses_parents(self):
        parent = WithDefaultPK.objects.create(value=1)
        obj = DefaultPKChild(withdefaultpk_ptr_id=parent.pk, value=2, child_value=3)
        with self.assertNumQueries(2):
            obj.save_base(raw=True)
        obj.child_value = 4
        with self.assertNumQueries(1):
            obj.save_base(raw=True)
        parent.refresh_from_db()
        self.assertEqual(parent.value, 1)
        self.assertEqual(DefaultPKChild.objects.get().child_value, 4)
