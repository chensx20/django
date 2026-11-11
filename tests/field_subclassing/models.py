import uuid

from django.db import models

from .fields import (
    CallableSlotField, CustomDescriptorField, GetterOnlyDescriptorField,
    InheritedCallableSlotField, NormalizingDescriptorField, PartialSlotField,
    StandaloneDescriptorField,
)


class CustomPrimaryKey(models.Model):
    key = CustomDescriptorField(primary_key=True, max_length=36, default=uuid.uuid4)
    flag = models.BooleanField(default=False)


class CustomPrimaryKeyChild(CustomPrimaryKey):
    pass


class StandalonePrimaryKey(models.Model):
    key = StandaloneDescriptorField(primary_key=True, max_length=36, default=uuid.uuid4)
    flag = models.BooleanField(default=False)


class StandalonePrimaryKeyChild(StandalonePrimaryKey):
    pass


class GetterOnlyPrimaryKey(models.Model):
    key = GetterOnlyDescriptorField(primary_key=True, max_length=36, default=uuid.uuid4)
    flag = models.BooleanField(default=False)
    label = GetterOnlyDescriptorField(max_length=36, default='label')


class GetterOnlyPrimaryKeyChild(GetterOnlyPrimaryKey):
    pass


class NormalizedPrimaryKey(models.Model):
    key = NormalizingDescriptorField(primary_key=True, max_length=36, default=uuid.uuid4)
    flag = models.BooleanField(default=False)


class NormalizedPrimaryKeyChild(NormalizedPrimaryKey):
    pass


class CallableSlotPrimaryKey(models.Model):
    key = CallableSlotField(primary_key=True, max_length=36, default=uuid.uuid4)
    flag = models.BooleanField(default=False)


class CallableSlotPrimaryKeyChild(CallableSlotPrimaryKey):
    pass


class InheritedCallableSlotPrimaryKey(models.Model):
    key = InheritedCallableSlotField(primary_key=True, max_length=36, default=uuid.uuid4)
    flag = models.BooleanField(default=False)


class InheritedCallableSlotPrimaryKeyChild(InheritedCallableSlotPrimaryKey):
    pass


class PartialSlotPrimaryKey(models.Model):
    key = PartialSlotField(primary_key=True, max_length=36, default=uuid.uuid4)
    flag = models.BooleanField(default=False)


class PartialSlotPrimaryKeyChild(PartialSlotPrimaryKey):
    pass
