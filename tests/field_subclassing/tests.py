from unittest import mock

from django.db import connection, models
from django.db.models.query_utils import field_attribute
from django.test import SimpleTestCase, TestCase

from .fields import CustomDescriptorField, CustomTypedField
from .models import (
    CustomPrimaryKey, CustomPrimaryKeyChild, GetterOnlyPrimaryKey,
    GetterOnlyPrimaryKeyChild, NormalizedPrimaryKey, NormalizedPrimaryKeyChild,
    StandalonePrimaryKey, StandalonePrimaryKeyChild,
)


class TestDbType(SimpleTestCase):

    def test_db_parameters_respects_db_type(self):
        f = CustomTypedField()
        self.assertEqual(f.db_parameters(connection)['type'], 'custom_field')


class DescriptorClassTest(SimpleTestCase):
    def test_descriptor_class(self):
        class CustomDescriptorModel(models.Model):
            name = CustomDescriptorField(max_length=32)

        m = CustomDescriptorModel()
        self.assertFalse(hasattr(m, '_name_get_count'))
        # The field is set to its default in the model constructor.
        self.assertEqual(m._name_set_count, 1)
        m.name = 'foo'
        self.assertFalse(hasattr(m, '_name_get_count'))
        self.assertEqual(m._name_set_count, 2)
        self.assertEqual(m.name, 'foo')
        self.assertEqual(m._name_get_count, 1)
        self.assertEqual(m._name_set_count, 2)
        m.name = 'bar'
        self.assertEqual(m._name_get_count, 1)
        self.assertEqual(m._name_set_count, 3)
        self.assertEqual(m.name, 'bar')
        self.assertEqual(m._name_get_count, 2)
        self.assertEqual(m._name_set_count, 3)


class PrimaryKeyDescriptorTests(TestCase):
    def test_named_inherited_reset(self):
        original = CustomPrimaryKeyChild.objects.create(key='original', flag=True)
        child = CustomPrimaryKeyChild.objects.get(pk=original.pk)
        setter_count = child._key_set_count
        with self.assertNumQueries(0):
            child.key = None
        self.assertEqual(child._key_set_count, setter_count + 1)
        self.assertIsNone(child.key)
        self.assertIsNone(child.customprimarykey_ptr_id)
        self.assertIsNone(child.pk)
        child.flag = False
        child.save()
        self.assertNotEqual(child.pk, original.pk)
        self.assertEqual(child.key, child.customprimarykey_ptr_id)
        self.assertEqual(CustomPrimaryKey.objects.count(), 2)
        self.assertEqual(CustomPrimaryKeyChild.objects.count(), 2)
        self.assertIs(CustomPrimaryKey.objects.get(pk=original.pk).flag, True)
        self.assertIs(CustomPrimaryKey.objects.get(pk=child.pk).flag, False)

    def test_construction_and_hydration(self):
        child = CustomPrimaryKeyChild(key=None, customprimarykey_ptr_id='original')
        self.assertEqual(child._key_set_count, 1)
        self.assertIsNone(child.key)
        self.assertEqual(child.pk, 'original')
        child = CustomPrimaryKeyChild.objects.create(key='original')
        loaded = CustomPrimaryKeyChild.objects.get(pk=child.pk)
        self.assertEqual(loaded._key_set_count, 1)
        self.assertEqual(loaded.key, 'original')
        self.assertEqual(loaded.pk, 'original')

    def test_refresh_calls_setter(self):
        child = CustomPrimaryKeyChild.objects.create(key='original')
        setter_count = child._key_set_count
        child.refresh_from_db()
        self.assertEqual(child._key_set_count, setter_count + 1)
        self.assertEqual(child.key, 'original')
        self.assertEqual(child.pk, 'original')

    def test_non_null_assignment_preserves_parent_link(self):
        child = CustomPrimaryKeyChild(key='original', customprimarykey_ptr_id='original')
        setter_count = child._key_set_count
        with self.assertNumQueries(0):
            child.key = 'changed'
        self.assertEqual(child._key_set_count, setter_count + 1)
        self.assertEqual(child.key, 'changed')
        self.assertEqual(child.pk, 'original')

    def test_deferred_read_uses_custom_getter(self):
        child = CustomPrimaryKeyChild.objects.create(key='original')
        loaded = CustomPrimaryKeyChild.objects.only('customprimarykey_ptr').get(pk=child.pk)
        self.assertNotIn('key', loaded.__dict__)
        with self.assertNumQueries(0):
            self.assertEqual(loaded.key, 'original')
        self.assertEqual(loaded._key_get_count, 1)
        with self.assertNumQueries(0):
            loaded.key = None
        self.assertIsNone(loaded.key)
        self.assertIsNone(loaded.pk)

    def test_internal_setter_error_restores_reset_interception(self):
        child = CustomPrimaryKeyChild(key='original', customprimarykey_ptr_id='original')
        field = CustomPrimaryKey._meta.pk
        with mock.patch.object(field.descriptor_access, 'write', side_effect=ValueError('invalid key')):
            with self.assertRaisesMessage(ValueError, 'invalid key'):
                child._set_field_value(field, 'changed')
        with self.assertNumQueries(0):
            child.key = None
        self.assertIsNone(child.key)
        self.assertIsNone(child.pk)

    def test_save_default_calls_setter(self):
        child = CustomPrimaryKeyChild(key=None)
        self.assertEqual(child._key_set_count, 1)
        child.save()
        self.assertEqual(child._key_set_count, 2)
        self.assertIsNotNone(child.pk)
        self.assertEqual(child.key, child.pk)
        self.assertTrue(CustomPrimaryKeyChild.objects.filter(pk=child.pk).exists())

    def test_delete_calls_setter(self):
        parent = CustomPrimaryKey.objects.create(key='original')
        setter_count = parent._key_set_count
        parent.delete()
        self.assertEqual(parent._key_set_count, setter_count + 1)
        self.assertIsNone(parent.key)
        self.assertIsNone(parent.pk)
        self.assertFalse(CustomPrimaryKey.objects.exists())

    def test_delete_keep_parents_preserves_identity(self):
        child = CustomPrimaryKeyChild.objects.create(key='original')
        setter_count = child._key_set_count
        child.delete(keep_parents=True)
        self.assertEqual(child._key_set_count, setter_count)
        self.assertEqual(child.key, 'original')
        self.assertIsNone(child.pk)
        self.assertTrue(CustomPrimaryKey.objects.filter(pk='original').exists())


class DescriptorProtocolTests(TestCase):
    def test_standalone_reset_preserves_original(self):
        for parent_model, child_model in (
            (StandalonePrimaryKey, StandalonePrimaryKeyChild),
            (GetterOnlyPrimaryKey, GetterOnlyPrimaryKeyChild),
        ):
            for reverse in (False, True):
                with self.subTest(model=child_model, reverse=reverse):
                    original = child_model.objects.create(flag=True)
                    parent = parent_model.objects.get(pk=original.pk)
                    relation = child_model._meta.parents[parent_model].remote_field
                    child = getattr(parent, relation.get_accessor_name()) if reverse else child_model.objects.get(
                        pk=original.pk,
                    )
                    key_access = parent_model._meta.pk.descriptor_access
                    link = child_model._meta.pk
                    link_access = link.descriptor_access
                    with mock.patch.object(key_access, 'write', wraps=key_access.write) as key_write:
                        with mock.patch.object(link_access, 'write', wraps=link_access.write) as link_write:
                            with self.assertNumQueries(0):
                                child.key = None
                            key_write.assert_called_once_with(child, None)
                            link_write.assert_called_once_with(child, None)
                    self.assertIsNone(child.key)
                    self.assertIsNone(child.pk)
                    self.assertIsNone(getattr(child, link.attname))
                    child.flag = False
                    child.save()
                    self.assertNotEqual(child.pk, original.pk)
                    self.assertEqual(child.key, child.pk)
                    self.assertIs(parent_model.objects.get(pk=original.pk).flag, True)
                    self.assertIs(parent_model.objects.get(pk=child.pk).flag, False)
                    self.assertEqual(parent.pk, str(original.pk))
                    self.assertIs(parent.flag, True)
                    if reverse:
                        self.assertIs(relation.is_cached(parent), False)
                        with self.assertNumQueries(1):
                            old_child = getattr(parent, relation.get_accessor_name())
                        self.assertEqual(old_child.pk, str(original.pk))
                        self.assertIsNot(old_child, child)
            self.assertEqual(parent_model.objects.count(), 4)
            self.assertEqual(child_model.objects.count(), 4)

    def test_explicit_standalone_key_preserves_original(self):
        for parent_model, child_model in (
            (StandalonePrimaryKey, StandalonePrimaryKeyChild),
            (GetterOnlyPrimaryKey, GetterOnlyPrimaryKeyChild),
        ):
            for reverse in (False, True):
                key = 'original-%s' % reverse
                with self.subTest(model=child_model, reverse=reverse):
                    child_model.objects.create(key=key, flag=True)
                    parent = parent_model.objects.get(pk=key)
                    relation = child_model._meta.pk.remote_field
                    if reverse:
                        child = getattr(parent, relation.get_accessor_name())
                    else:
                        child = child_model.objects.get(pk=key)
                    with self.assertNumQueries(0):
                        child.key = None
                    self.assertIsNone(child.key)
                    self.assertIsNone(child.pk)
                    child.flag = False
                    child.save()
                    self.assertNotEqual(child.pk, key)
                    self.assertEqual(child.pk, child.key)
                    self.assertIs(parent_model.objects.get(pk=key).flag, True)
                    self.assertIs(parent_model.objects.get(pk=child.pk).flag, False)
            self.assertEqual(parent_model.objects.count(), 4)
            self.assertEqual(child_model.objects.count(), 4)

    def test_reset_paths_and_missing_or_none_key(self):
        for parent_model, child_model in (
            (CustomPrimaryKey, CustomPrimaryKeyChild),
            (StandalonePrimaryKey, StandalonePrimaryKeyChild),
            (GetterOnlyPrimaryKey, GetterOnlyPrimaryKeyChild),
        ):
            for name in ('key', 'pk'):
                for state in ('loaded', 'deferred', 'none', 'new'):
                    with self.subTest(model=child_model, name=name, state=state):
                        original = child_model.objects.create(flag=True)
                        link = child_model._meta.pk
                        if state == 'new':
                            child = child_model(**{link.attname: original.pk})
                        elif state == 'deferred':
                            child = child_model.objects.only(link.name).get(pk=original.pk)
                            self.assertNotIn('key', child.__dict__)
                        else:
                            child = child_model.objects.get(pk=original.pk)
                            if state == 'none':
                                child._set_field_value(parent_model._meta.pk, None)
                        access = parent_model._meta.pk.descriptor_access
                        with mock.patch.object(access, 'write', wraps=access.write) as write:
                            with self.assertNumQueries(0):
                                setattr(child, name, None)
                            write.assert_called_once_with(child, None)
                        self.assertIsNone(child.key)
                        self.assertIsNone(child.pk)
                        child.flag = False
                        if parent_model is GetterOnlyPrimaryKey:
                            child.label = 'clone'
                        child.save()
                        self.assertNotEqual(child.pk, original.pk)
                        self.assertIs(parent_model.objects.get(pk=original.pk).flag, True)

    def test_getter_only_precedence_and_deferred_reads(self):
        original = GetterOnlyPrimaryKeyChild.objects.create(key='original')
        self.assertNotIn('_key_get_count', original.__dict__)
        self.assertEqual(original.key, 'original')
        self.assertEqual(original.label, 'label')
        self.assertNotIn('_key_get_count', original.__dict__)
        self.assertNotIn('_label_get_count', original.__dict__)
        child = GetterOnlyPrimaryKeyChild.objects.only('getteronlyprimarykey_ptr').get(pk=original.pk)
        with self.assertNumQueries(0):
            self.assertEqual(child.key, 'original')
        self.assertEqual(child._key_get_count, 1)
        with self.assertNumQueries(1):
            self.assertEqual(child.label, 'label')
        self.assertEqual(child._label_get_count, 1)
        with self.assertNumQueries(0):
            self.assertEqual(child.label, 'label')
        self.assertEqual(child._label_get_count, 1)
        del child.label
        with self.assertNumQueries(1):
            self.assertEqual(child.label, 'label')

    def test_class_access_and_custom_getter_results(self):
        self.assertEqual(StandalonePrimaryKey.key, 'descriptor for key')
        self.assertEqual(GetterOnlyPrimaryKey.key, 'getter for key')
        self.assertEqual(NormalizedPrimaryKey.key, 'normalized key')
        descriptor = CustomPrimaryKey._meta.pk.descriptor_access.descriptor
        self.assertIs(CustomPrimaryKey.key, descriptor)
        parent = NormalizedPrimaryKey(key='UPPER')
        self.assertEqual(parent.key, 'upper')
        self.assertNotIn('key', parent.__dict__)

    def test_owned_storage_lifecycle(self):
        parent = NormalizedPrimaryKey(key='UPPER')
        self.assertEqual(parent._key_set_count, 1)
        self.assertEqual(parent.key, 'upper')
        parent.key = 'CHANGED'
        self.assertEqual(parent.key, 'changed')
        self.assertEqual(parent._key_set_count, 2)
        parent.save()
        loaded = NormalizedPrimaryKey.objects.get(pk=parent.pk)
        self.assertEqual(loaded._key_set_count, 1)
        self.assertEqual(loaded.key, 'changed')
        loaded.refresh_from_db(fields=['key'])
        self.assertEqual(loaded._key_set_count, 2)
        loaded.delete()
        self.assertIsNone(loaded.key)
        self.assertEqual(loaded._key_set_count, 3)
        child = NormalizedPrimaryKeyChild(key=None)
        child.save()
        self.assertEqual(child._key_set_count, 2)
        self.assertEqual(child.key, child.pk)
        self.assertNotIn('key', child.__dict__)
        with self.assertNumQueries(0):
            child.key = None
        self.assertEqual(child._key_set_count, 3)
        self.assertIsNone(child.key)
        self.assertIsNone(child.pk)

    def test_setter_rejection_and_nested_suppression(self):
        child = NormalizedPrimaryKeyChild(key='original', normalizedprimarykey_ptr_id='original')
        child._reject_none = True
        with self.assertRaisesMessage(ValueError, 'None is not a key'):
            child.key = None
        self.assertEqual(child.key, 'original')
        self.assertNotIn('key', child.__dict__)
        self.assertIs(child._state.setting_field, False)
        child._reject_none = False
        access = NormalizedPrimaryKey._meta.pk.descriptor_access
        write = access.write

        def nested_write(instance, value):
            self.assertIs(instance._state.setting_field, True)
            instance._set_field_value(NormalizedPrimaryKey._meta.get_field('flag'), False)
            self.assertIs(instance._state.setting_field, True)
            write(instance, value)

        with mock.patch.object(access, 'write', side_effect=nested_write):
            child._set_field_value(NormalizedPrimaryKey._meta.pk, 'CHANGED')
        self.assertIs(child._state.setting_field, False)
        self.assertEqual(child.key, 'changed')
        with self.assertNumQueries(0):
            child.key = None
        self.assertIsNone(child.key)
        self.assertIsNone(child.pk)

    def test_constructor_error_restores_suppression(self):
        child = NormalizedPrimaryKeyChild.__new__(NormalizedPrimaryKeyChild)
        child._reject_none = True
        with self.assertRaisesMessage(ValueError, 'None is not a key'):
            child.__init__(key=None)
        self.assertIs(child._state.initializing, False)

    def test_standalone_internal_writer_counts(self):
        for parent_model, child_model in (
            (StandalonePrimaryKey, StandalonePrimaryKeyChild),
            (GetterOnlyPrimaryKey, GetterOnlyPrimaryKeyChild),
            (NormalizedPrimaryKey, NormalizedPrimaryKeyChild),
        ):
            with self.subTest(model=child_model):
                access = parent_model._meta.pk.descriptor_access
                with mock.patch.object(access, 'write', wraps=access.write) as write:
                    child = child_model(key='original')
                    self.assertEqual(write.call_count, 1)
                    child.save()
                    write.reset_mock()
                    loaded = child_model.objects.get(pk=child.pk)
                    write.assert_called_once_with(loaded, 'original')
                    write.reset_mock()
                    loaded.refresh_from_db(fields=['key'])
                    self.assertEqual(write.call_count, 2)  # Hydration and assignment.
                    write.reset_mock()
                    loaded.delete(keep_parents=True)
                    write.assert_not_called()
                    self.assertEqual(loaded.key, 'original')
                    self.assertIsNone(loaded.pk)
                    parent = parent_model.objects.get(pk='original')
                    write.reset_mock()
                    parent.delete()
                    write.assert_called_once_with(parent, None)
                    self.assertIsNone(parent.key)
                    child = child_model.objects.create(key='collected')
                    write.reset_mock()
                    child.delete()
                    self.assertEqual(write.call_count, 2)
                    collected_parent = write.call_args_list[0][0][0]
                    self.assertIs(type(collected_parent), parent_model)
                    self.assertEqual(write.call_args_list, [
                        mock.call(collected_parent, 'collected'),
                        mock.call(collected_parent, None),
                    ])
                    self.assertIsNone(collected_parent.key)
                    self.assertEqual(child.key, 'collected')
                    self.assertIsNone(child.pk)
                    self.assertIs(parent_model.objects.exists(), False)

    def test_nonnull_assignment_does_not_synchronize_links(self):
        child = NormalizedPrimaryKeyChild.objects.create(key='original')
        count = child._key_set_count
        child.key = 'CHANGED'
        self.assertEqual(child.key, 'changed')
        self.assertEqual(child.pk, 'original')
        self.assertEqual(child._key_set_count, count + 1)

    def test_descriptor_protocol_registration_and_deletion(self):
        class Descriptor:
            def __init__(self, field):
                self.field = field

            def __get__(self, instance, owner):
                return 'class result' if instance is None else 'custom result'

            def __set__(self, instance, value):
                instance.__dict__['stored'] = value

            def __delete__(self, instance):
                del instance.__dict__['stored']

        field = models.CharField()
        field.set_attributes_from_name('value')
        field.descriptor_class = Descriptor
        with mock.patch.object(field, 'descriptor_class', wraps=Descriptor) as factory:
            attribute = field_attribute(field)
        factory.assert_called_once_with(field)
        instance = StandalonePrimaryKey(key='original')
        attribute.__set__(instance, 'stored value')
        self.assertEqual(attribute.__get__(None, type(instance)), 'class result')
        self.assertEqual(attribute.__get__(instance, type(instance)), 'custom result')
        attribute.__delete__(instance)
        self.assertNotIn('stored', instance.__dict__)
        with self.assertRaises(KeyError):
            attribute.__delete__(instance)

        class DeleteOnlyDescriptor(Descriptor):
            __set__ = None

        field.descriptor_class = DeleteOnlyDescriptor
        with self.assertRaisesMessage(TypeError, 'Field descriptor __set__ must be callable.'):
            field_attribute(field)

        class GetterAndDeleter:
            def __init__(self, field):
                pass

            def __get__(self, instance, owner):
                return 'value'

            def __delete__(self, instance):
                del instance.__dict__['stored']

        field.descriptor_class = GetterAndDeleter
        attribute = field_attribute(field)
        with self.assertRaisesMessage(AttributeError, '__set__'):
            attribute.__set__(instance, 'invalid')
        self.assertNotIn('value', instance.__dict__)
        with self.assertRaisesMessage(AttributeError, '__delete__'):
            StandalonePrimaryKey.__dict__['key'].__delete__(instance)

        class InvalidGetter(Descriptor):
            __get__ = None

        field.descriptor_class = InvalidGetter
        with self.assertRaisesMessage(TypeError, 'Field descriptors must define a callable __get__.'):
            field_attribute(field)

        class InvalidDeleter(Descriptor):
            __delete__ = None

        field.descriptor_class = InvalidDeleter
        with self.assertRaisesMessage(TypeError, 'Field descriptor __delete__ must be callable.'):
            field_attribute(field)
