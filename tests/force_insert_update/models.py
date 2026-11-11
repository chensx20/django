"""
Tests for forcing insert and update queries (instead of Django's normal
automatic behavior).
"""
import uuid

from field_subclassing.fields import CustomDescriptorField

from django.db import models


class Counter(models.Model):
    name = models.CharField(max_length=10)
    value = models.IntegerField()


class InheritedCounter(Counter):
    tag = models.CharField(max_length=10)


class ProxyCounter(Counter):
    class Meta:
        proxy = True


class SubCounter(Counter):
    pass


class WithCustomPK(models.Model):
    name = models.IntegerField(primary_key=True)
    value = models.IntegerField()


class WithDefaultPK(models.Model):
    key = models.UUIDField(primary_key=True, default=uuid.uuid4)
    value = models.IntegerField(default=0)


class WithFalsyDefaultPK(models.Model):
    key = models.IntegerField(primary_key=True, default=0)
    value = models.IntegerField(default=0)


class WithCustomDescriptorPK(models.Model):
    key = CustomDescriptorField(primary_key=True, max_length=36, default=uuid.uuid4)
    value = models.IntegerField(default=0)


class DefaultPKChild(WithDefaultPK):
    child_value = models.IntegerField(default=0)


class DefaultPKGrandchild(DefaultPKChild):
    grandchild_value = models.IntegerField(default=0)


class DefaultPKProxy(WithDefaultPK):
    class Meta:
        proxy = True


class AbstractDefaultPK(models.Model):
    key = models.UUIDField(primary_key=True, default=uuid.uuid4)

    class Meta:
        abstract = True


class ConcreteDefaultPK(AbstractDefaultPK):
    value = models.IntegerField(default=0)
