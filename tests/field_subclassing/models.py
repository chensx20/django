import uuid

from django.db import models

from .fields import CustomDescriptorField


class CustomPrimaryKey(models.Model):
    key = CustomDescriptorField(primary_key=True, max_length=36, default=uuid.uuid4)
    flag = models.BooleanField(default=False)


class CustomPrimaryKeyChild(CustomPrimaryKey):
    pass
