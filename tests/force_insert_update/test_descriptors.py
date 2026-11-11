import inspect
from types import SimpleNamespace

from django.db import models
from django.db.models import signals
from django.db.models.query_utils import PrimaryKeyDeferredAttribute
from django.test import SimpleTestCase
from django.test.utils import isolate_apps


class Getter:
    def __get__(self, instance, owner):
        self.reads.append((instance, owner))
        return self if instance is None else instance.storage


class Setter:
    def __set__(self, instance, value):
        instance.calls.append(('set', value))
        instance.storage = value.upper()
        if instance.fail:
            raise ValueError('set failed')


class Deleter:
    def __delete__(self, instance):
        instance.calls.append(('delete',))
        del instance.storage
        if instance.fail:
            raise ValueError('delete failed')


class PrimaryKeyDescriptorTests(SimpleTestCase):
    def make_instance(self, descriptor):
        class Instance:
            key = PrimaryKeyDeferredAttribute(SimpleNamespace(attname='key'), descriptor)

        obj = Instance()
        obj._generated_pk_fields = frozenset({'key', 'other'})
        obj.storage = 'computed'
        obj.calls = []
        obj.fail = False
        return obj

    def descriptor(self, *bases):
        descriptor = type('Descriptor', bases, {})()
        descriptor.reads = []
        return descriptor

    def test_non_data_dictionary_precedence_and_deletion(self):
        descriptor = self.descriptor(Getter)
        obj = self.make_instance(descriptor)
        obj.key = 'explicit'
        self.assertEqual(obj.key, 'explicit')
        self.assertEqual(descriptor.reads, [])
        self.assertEqual(obj._generated_pk_fields, {'other'})
        obj._generated_pk_fields |= {'key'}
        del obj.key
        self.assertEqual(obj._generated_pk_fields, {'other'})
        self.assertEqual(obj.key, 'computed')
        self.assertEqual(descriptor.reads, [(obj, type(obj))])
        with self.assertRaisesMessage(AttributeError, 'key'):
            del obj.key

    def test_data_getter_precedence(self):
        for bases in ((Getter, Setter), (Getter, Deleter), (Getter, Setter, Deleter)):
            with self.subTest(bases=bases):
                descriptor = self.descriptor(*bases)
                obj = self.make_instance(descriptor)
                obj.__dict__['key'] = 'shadow'
                self.assertEqual(obj.key, 'computed')
                self.assertEqual(descriptor.reads, [(obj, type(obj))])

    def test_setter_without_deleter(self):
        obj = self.make_instance(self.descriptor(Getter, Setter))
        obj.key = 'explicit'
        self.assertEqual(obj.key, 'EXPLICIT')
        self.assertEqual(obj.calls, [('set', 'explicit')])
        obj._generated_pk_fields |= {'key'}
        obj.__dict__['key'] = 'untouched'
        with self.assertRaisesMessage(AttributeError, '__delete__'):
            del obj.key
        self.assertEqual(obj.__dict__['key'], 'untouched')
        self.assertEqual(obj._generated_pk_fields, {'key', 'other'})
        self.assertEqual(obj.calls, [('set', 'explicit')])

    def test_deleter_without_setter(self):
        obj = self.make_instance(self.descriptor(Getter, Deleter))
        with self.assertRaisesMessage(AttributeError, '__set__'):
            obj.key = 'explicit'
        self.assertNotIn('key', obj.__dict__)
        self.assertEqual(obj._generated_pk_fields, {'key', 'other'})
        del obj.key
        self.assertEqual(obj.calls, [('delete',)])
        self.assertFalse(hasattr(obj, 'storage'))
        self.assertEqual(obj._generated_pk_fields, {'other'})

    def test_custom_mutations_and_failures(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                obj = self.make_instance(self.descriptor(Getter, Setter, Deleter))
                obj.fail = fail
                obj.__dict__['key'] = 'untouched'
                if fail:
                    with self.assertRaisesMessage(ValueError, 'set failed'):
                        obj.key = 'explicit'
                else:
                    obj.key = 'explicit'
                self.assertEqual(obj.storage, 'EXPLICIT')
                self.assertEqual(obj._generated_pk_fields, {'other'})
                obj._generated_pk_fields |= {'key'}
                if fail:
                    with self.assertRaisesMessage(ValueError, 'delete failed'):
                        del obj.key
                else:
                    del obj.key
                self.assertEqual(obj.calls, [('set', 'explicit'), ('delete',)])
                self.assertFalse(hasattr(obj, 'storage'))
                self.assertEqual(obj.__dict__['key'], 'untouched')
                self.assertEqual(obj._generated_pk_fields, {'other'})

    def test_no_getter_protocols(self):
        for bases in ((), (Setter,), (Deleter,), (Setter, Deleter)):
            with self.subTest(bases=bases):
                descriptor = self.descriptor(*bases)
                obj = self.make_instance(descriptor)
                self.assertIs(type(obj).key, descriptor)
                self.assertIs(obj.key, descriptor)
                obj.__dict__['key'] = 'shadow'
                self.assertEqual(obj.key, 'shadow')
                if bases == (Deleter,):
                    with self.assertRaisesMessage(AttributeError, '__set__'):
                        obj.key = 'explicit'
                    self.assertEqual(obj._generated_pk_fields, {'key', 'other'})
                else:
                    obj.key = 'explicit'
                    self.assertEqual(obj._generated_pk_fields, {'other'})
                    if Setter in bases:
                        self.assertEqual(obj.storage, 'EXPLICIT')
                        self.assertEqual(obj.key, 'shadow')
                    else:
                        self.assertEqual(obj.key, 'explicit')
                obj._generated_pk_fields |= {'key'}
                if bases == (Setter,):
                    with self.assertRaisesMessage(AttributeError, '__delete__'):
                        del obj.key
                    self.assertEqual(obj._generated_pk_fields, {'key', 'other'})
                else:
                    del obj.key
                    self.assertEqual(obj._generated_pk_fields, {'other'})
                    if Deleter in bases:
                        self.assertFalse(hasattr(obj, 'storage'))
                        self.assertEqual(obj.key, 'shadow')
                    else:
                        self.assertIs(obj.key, descriptor)

    def test_class_access_and_inherited_hooks(self):
        descriptor = self.descriptor(Getter, Setter, Deleter)
        obj = self.make_instance(descriptor)

        class Child(type(obj)):
            pass

        self.assertIs(Child.key, descriptor)
        self.assertEqual(descriptor.reads, [(None, Child)])
        obj.key = 'explicit'
        self.assertEqual(obj.key, 'EXPLICIT')
        del obj.key
        self.assertEqual(obj.calls, [('set', 'explicit'), ('delete',)])

    def test_instance_pseudo_hooks_are_ignored(self):
        class Descriptor:
            def __getattr__(self, name):
                raise AssertionError('Instance special-method lookup: %s' % name)

        descriptor = Descriptor()
        descriptor.__get__ = lambda *args: self.fail('pseudo getter')
        descriptor.__set__ = lambda *args: self.fail('pseudo setter')
        descriptor.__delete__ = lambda *args: self.fail('pseudo deleter')
        obj = self.make_instance(descriptor)
        self.assertIs(obj.key, descriptor)
        obj.key = 'explicit'
        self.assertEqual(obj.key, 'explicit')
        del obj.key
        self.assertIs(obj.key, descriptor)
        descriptor = self.descriptor(Getter)
        descriptor.__set__ = lambda *args: self.fail('pseudo setter')
        descriptor.__delete__ = lambda *args: self.fail('pseudo deleter')
        obj = self.make_instance(descriptor)
        obj.key = 'explicit'
        self.assertEqual(obj.key, 'explicit')
        self.assertEqual(descriptor.reads, [])
        del obj.key
        self.assertEqual(obj.key, 'computed')

    def test_custom_return_values_and_getter_exception(self):
        token = object()

        class Descriptor:
            def __get__(self, instance, owner):
                if instance is None:
                    return owner
                raise ValueError('get failed')

            def __set__(self, instance, value):
                return token

            def __delete__(self, instance):
                return token

        obj = self.make_instance(Descriptor())
        adapter = inspect.getattr_static(type(obj), 'key')
        self.assertIs(type(obj).key, type(obj))
        self.assertIs(adapter.__set__(obj, 'explicit'), token)
        self.assertIs(adapter.__delete__(obj), token)
        obj.__dict__['key'] = 'untouched'
        with self.assertRaisesMessage(ValueError, 'get failed'):
            obj.key
        self.assertEqual(obj.__dict__['key'], 'untouched')

    def test_static_and_class_hooks(self):
        class Descriptor:
            @staticmethod
            def __get__(instance, owner):
                return owner if instance is None else instance.storage

            @classmethod
            def __set__(cls, instance, value):
                instance.storage = (cls, value)

        obj = self.make_instance(Descriptor())
        obj.key = 'explicit'
        self.assertEqual(obj.key, (Descriptor, 'explicit'))
        self.assertIs(type(obj).key, type(obj))

    def test_non_callable_hooks_are_not_missing(self):
        for name in ('__get__', '__set__', '__delete__'):
            with self.subTest(name=name):
                descriptor = type('Descriptor', (), {name: None})()
                obj = self.make_instance(descriptor)
                with self.assertRaisesMessage(TypeError, "'NoneType' object is not callable"):
                    if name == '__get__':
                        obj.key
                    elif name == '__set__':
                        obj.key = 'explicit'
                    else:
                        del obj.key
                self.assertNotIn('key', obj.__dict__)
                self.assertEqual(obj._generated_pk_fields, {'key', 'other'} if name == '__get__' else {'other'})
                if name == '__set__':
                    obj._generated_pk_fields |= {'key'}
                    with self.assertRaisesMessage(AttributeError, '__delete__'):
                        del obj.key
                    self.assertIn('key', obj._generated_pk_fields)
                elif name == '__delete__':
                    obj._generated_pk_fields |= {'key'}
                    with self.assertRaisesMessage(AttributeError, '__set__'):
                        obj.key = 'explicit'
                    self.assertIn('key', obj._generated_pk_fields)
                if name != '__set__':
                    obj.__dict__['key'] = 'shadow'
                    self.assertEqual(obj.key, 'shadow')


@isolate_apps('force_insert_update')
class PrimaryKeyRegistrationTests(SimpleTestCase):
    def test_replacement_before_class_prepared(self):
        class Descriptor(Getter, Setter):
            reads = []

            def __set_name__(self, owner, name):
                raise AssertionError('Unexpected initialization callback')

        descriptor = Descriptor()

        class Field(models.CharField):
            def contribute_to_class(self, cls, name, **kwargs):
                super().contribute_to_class(cls, name, **kwargs)
                setattr(cls, self.attname, descriptor)

        prepared = []

        def receiver(sender, **kwargs):
            prepared.append(inspect.getattr_static(sender, 'key'))

        signals.class_prepared.connect(receiver)
        try:
            class Replacement(models.Model):
                key = Field(primary_key=True, max_length=32, default='generated')

                def __init__(self, *args, **kwargs):
                    self.calls = []
                    self.fail = False
                    super().__init__(*args, **kwargs)
        finally:
            signals.class_prepared.disconnect(receiver)
        adapter = inspect.getattr_static(Replacement, 'key')
        self.assertEqual(prepared, [adapter])
        self.assertIs(adapter.descriptor, descriptor)
        obj = Replacement()
        self.assertEqual(obj.key, 'GENERATED')
        obj.key = obj.key
        self.assertNotIn('key', obj._generated_pk_fields)

    def test_promoted_parent_link_and_inherited_adapters(self):
        class Parent(models.Model):
            key = models.CharField(primary_key=True, max_length=32, default='generated')

        original = inspect.getattr_static(Parent, 'key')

        class Child(Parent):
            parent = models.OneToOneField(Parent, on_delete=models.CASCADE, parent_link=True)

        class Grandchild(Child):
            pass

        class Proxy(Grandchild):
            class Meta:
                proxy = True

        self.assertIs(Child._meta.pk, Child._meta.get_field('parent'))
        for model in (Child, Grandchild, Proxy):
            self.assertIs(inspect.getattr_static(model, 'key'), original)
            self.assertIs(inspect.getattr_static(model, 'parent_id'), inspect.getattr_static(Child, 'parent_id'))
        adapter = inspect.getattr_static(Child, 'parent_id')
        self.assertIsInstance(adapter, PrimaryKeyDeferredAttribute)
        self.assertNotIsInstance(adapter.descriptor, PrimaryKeyDeferredAttribute)
        parent = Parent()
        obj = Child(parent=parent)
        self.assertIs(obj.parent, parent)
        obj._generated_pk_fields |= {'parent_id'}
        obj.parent_id = 'explicit'
        self.assertNotIn('parent_id', obj._generated_pk_fields)
        self.assertFalse(Child._meta.pk.is_cached(obj))

    def test_abstract_field_and_unrelated_descriptor(self):
        class Abstract(models.Model):
            key = models.CharField(primary_key=True, max_length=32, default='generated')
            name = models.CharField(max_length=32)

            class Meta:
                abstract = True

        original = inspect.getattr_static(Abstract, 'key')

        class Concrete(Abstract):
            pass

        class Other(Abstract):
            pass

        self.assertIs(inspect.getattr_static(Abstract, 'key'), original)
        self.assertNotIsInstance(original, PrimaryKeyDeferredAttribute)
        for model in (Concrete, Other):
            adapter = inspect.getattr_static(model, 'key')
            self.assertIsInstance(adapter, PrimaryKeyDeferredAttribute)
            self.assertNotIsInstance(adapter.descriptor, PrimaryKeyDeferredAttribute)
            self.assertNotIsInstance(inspect.getattr_static(model, 'name'), PrimaryKeyDeferredAttribute)
        self.assertIsNot(inspect.getattr_static(Concrete, 'key'), inspect.getattr_static(Other, 'key'))

    def test_read_only_constructor_still_fails(self):
        class Descriptor(Getter, Deleter):
            def __init__(self, field):
                self.field = field

        class Field(models.CharField):
            descriptor_class = Descriptor

        class ReadOnly(models.Model):
            key = Field(primary_key=True, max_length=32, default='generated')

        with self.assertRaisesMessage(AttributeError, '__set__'):
            ReadOnly(key='explicit')
