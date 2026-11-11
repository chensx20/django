from unittest import mock

from django.db import connection, models
from django.test import SimpleTestCase, TestCase

from .fields import CustomDescriptorField, CustomTypedField
from .models import CustomPrimaryKey, CustomPrimaryKeyChild


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
        descriptor = CustomPrimaryKey.__dict__['key']
        with mock.patch.object(descriptor, '_set_value', side_effect=ValueError('invalid key')):
            with self.assertRaisesMessage(ValueError, 'invalid key'):
                child._set_field_value(descriptor.field, 'changed')
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
