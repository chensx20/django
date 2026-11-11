from functools import partial

from django.db import models
from django.db.models.query_utils import DeferredAttribute


class CustomTypedField(models.TextField):
    def db_type(self, connection):
        return 'custom_field'


class CustomDeferredAttribute(DeferredAttribute):
    def __get__(self, instance, cls=None):
        if instance is not None:
            self._count_call(instance, 'get')
        return super().__get__(instance, cls)

    def __set__(self, instance, value):
        self._count_call(instance, 'set')
        instance.__dict__[self.field.attname] = value

    def _count_call(self, instance, get_or_set):
        count_attr = '_%s_%s_count' % (self.field.attname, get_or_set)
        count = getattr(instance, count_attr, 0)
        setattr(instance, count_attr, count + 1)


class CustomDescriptorField(models.CharField):
    descriptor_class = CustomDeferredAttribute


class StandaloneDescriptor:
    def __init__(self, field):
        self.field = field
        self.deferred = DeferredAttribute(field)

    def __get__(self, instance, owner=None):
        if instance is None:
            return 'descriptor for %s' % self.field.name
        return self.deferred.__get__(instance, owner)

    def __set__(self, instance, value):
        count_name = '_%s_set_count' % self.field.attname
        instance.__dict__[count_name] = instance.__dict__.get(count_name, 0) + 1
        instance.__dict__[self.field.attname] = value


class StandaloneDescriptorField(models.CharField):
    descriptor_class = StandaloneDescriptor


class GetterOnlyDescriptor:
    def __init__(self, field):
        self.field = field
        self.deferred = DeferredAttribute(field)

    def __get__(self, instance, owner=None):
        if instance is None:
            return 'getter for %s' % self.field.name
        count_name = '_%s_get_count' % self.field.attname
        instance.__dict__[count_name] = instance.__dict__.get(count_name, 0) + 1
        return self.deferred.__get__(instance, owner)


class GetterOnlyDescriptorField(models.CharField):
    descriptor_class = GetterOnlyDescriptor


class NormalizingDescriptor(StandaloneDescriptor):
    def __get__(self, instance, owner=None):
        if instance is None:
            return 'normalized %s' % self.field.name
        return instance.__dict__['_stored_%s' % self.field.attname]

    def __set__(self, instance, value):
        if value is None and instance.__dict__.get('_reject_none', False):
            raise ValueError('None is not a key')
        count_name = '_%s_set_count' % self.field.attname
        instance.__dict__[count_name] = instance.__dict__.get(count_name, 0) + 1
        instance.__dict__['_stored_%s' % self.field.attname] = None if value is None else str(value).lower()


class NormalizingDescriptorField(models.CharField):
    descriptor_class = NormalizingDescriptor


class ReadSlot:
    def __call__(self, descriptor, instance, owner=None):
        return StandaloneDescriptor.__get__(descriptor, instance, owner)


class WriteSlot:
    def __call__(self, instance, value):
        instance.__dict__['_key_set_count'] = instance.__dict__.get('_key_set_count', 0) + 1
        instance.__dict__['key'] = value


class DeleteSlot:
    def __call__(self, instance):
        del instance.__dict__['key']


class CallableSlotDescriptor(StandaloneDescriptor):
    __get__ = ReadSlot()
    __set__ = WriteSlot()
    __delete__ = DeleteSlot()


class BindingReadSlot(ReadSlot):
    def __get__(self, instance, owner):
        raise AssertionError('Callable protocol slots must not be bound.')


class BindingWriteSlot(WriteSlot):
    def __get__(self, instance, owner):
        return partial(StandaloneDescriptor.__set__, instance)


class BindingDeleteSlot(DeleteSlot):
    def __get__(self, instance, owner):
        return DeleteSlot()


class BindingSlotDescriptor(StandaloneDescriptor):
    __get__ = BindingReadSlot()
    __set__ = BindingWriteSlot()
    __delete__ = BindingDeleteSlot()


class InheritedCallableSlotDescriptor(BindingSlotDescriptor):
    pass


class PartialSlotDescriptor(StandaloneDescriptor):
    __get__ = partial(StandaloneDescriptor.__get__)
    __set__ = partial(WriteSlot())
    __delete__ = partial(DeleteSlot())


class BoundMethodSlotDescriptor(StandaloneDescriptor):
    __get__ = ReadSlot().__call__
    __set__ = WriteSlot().__call__
    __delete__ = DeleteSlot().__call__


class StaticSlotDescriptor(StandaloneDescriptor):
    __get__ = ReadSlot()
    __set__ = staticmethod(WriteSlot())
    __delete__ = staticmethod(DeleteSlot())


class ClassSlotDescriptor(StandaloneDescriptor):
    __get__ = ReadSlot()

    @classmethod
    def __set__(cls, instance, value):
        WriteSlot()(instance, value)

    @classmethod
    def __delete__(cls, instance):
        DeleteSlot()(instance)


class CallableSlotField(models.CharField):
    descriptor_class = CallableSlotDescriptor


class InheritedCallableSlotField(models.CharField):
    descriptor_class = InheritedCallableSlotDescriptor


class PartialSlotField(models.CharField):
    descriptor_class = PartialSlotDescriptor
