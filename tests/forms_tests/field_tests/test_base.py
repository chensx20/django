import copy
from unittest import mock

from django.core.exceptions import ValidationError
from django.forms import (
    ChoiceField, Field, Form, ModelChoiceField, Select, SplitDateTimeField,
)
from django.test import SimpleTestCase
from django.utils.functional import Promise, lazy


class BasicFieldsTests(SimpleTestCase):

    def test_deepcopy_error_messages(self):
        field = Field(error_messages={'required': 'Original', 'custom': 'Custom'})
        original = field.error_messages.copy()
        first = copy.deepcopy(field)
        second = copy.deepcopy(field)
        self.assertEqual(first.error_messages, original)
        self.assertIsNot(first.error_messages, field.error_messages)
        self.assertIsNot(first.error_messages, second.error_messages)
        first.error_messages['required'] = 'Changed'
        first.error_messages['extra'] = 'Extra'
        del first.error_messages['custom']
        self.assertEqual(field.error_messages, original)
        self.assertEqual(second.error_messages, original)

    def test_deepcopy_error_messages_nested_values(self):
        field = Field(error_messages={'custom': {'messages': ['Original']}})
        clone = copy.deepcopy(field)
        self.assertIsNot(clone.error_messages['custom'], field.error_messages['custom'])
        self.assertIsNot(clone.error_messages['custom']['messages'], field.error_messages['custom']['messages'])
        clone.error_messages['custom']['messages'].append('Copied')
        self.assertEqual(field.error_messages['custom']['messages'], ['Original'])
        field.error_messages['custom']['messages'].append('Source')
        self.assertEqual(clone.error_messages['custom']['messages'], ['Original', 'Copied'])

    def test_deepcopy_error_messages_aliases(self):
        messages = ['Original']
        first = Field(error_messages={'custom': messages, 'alias': messages})
        second = Field(error_messages={'custom': messages})
        first_clone, second_clone = copy.deepcopy([first, second])
        self.assertIsNot(first_clone.error_messages['custom'], messages)
        self.assertIs(first_clone.error_messages['custom'], first_clone.error_messages['alias'])
        self.assertIs(first_clone.error_messages['custom'], second_clone.error_messages['custom'])

    def test_deepcopy_error_messages_memo(self):
        messages = ['Original']
        replacement = ['Replacement']
        field = Field(error_messages={'custom': messages})
        memo = {id(messages): replacement}
        received_memos = []

        class Message:
            def __deepcopy__(self, memo):
                received_memos.append(memo)
                return memo[id(field)]

        field.error_messages['owner'] = Message()
        clone = copy.deepcopy(field, memo)
        self.assertIs(clone.error_messages['custom'], replacement)
        self.assertEqual(len(received_memos), 1)
        self.assertIs(received_memos[0], memo)
        self.assertIs(clone.error_messages['owner'], clone)

    def test_deepcopy_error_messages_cycles(self):
        field = Field()
        field.error_messages['self'] = field.error_messages
        field.error_messages['field'] = field
        clone = copy.deepcopy(field)
        self.assertIsNot(clone.error_messages, field.error_messages)
        self.assertIs(clone.error_messages['self'], clone.error_messages)
        self.assertIs(clone.error_messages['field'], clone)

    def test_deepcopy_error_messages_lazy(self):
        message = mock.Mock(return_value='Required lazily')
        field = Field(error_messages={'required': lazy(message, str)()})
        clone = copy.deepcopy(field)
        message.assert_not_called()
        self.assertIsInstance(clone.error_messages['required'], Promise)
        self.assertIsInstance(copy.deepcopy(Field()).error_messages['required'], Promise)
        self.assertIsNot(clone.error_messages, field.error_messages)
        with self.assertRaisesMessage(ValidationError, 'Required lazily'):
            clone.clean('')
        message.assert_called_once_with()

    def test_deepcopy_error_messages_subclasses(self):
        fields = [
            ChoiceField(choices=[('a', 'A')]),
            SplitDateTimeField(),
            ModelChoiceField(queryset=None),
        ]
        for field in fields:
            with self.subTest(field=type(field)):
                field.error_messages['custom'] = ['Original']
                clone = copy.deepcopy(field)
                self.assertIs(type(clone), type(field))
                self.assertEqual(clone.error_messages, field.error_messages)
                self.assertIsNot(clone.error_messages['custom'], field.error_messages['custom'])
        field = SplitDateTimeField()
        field.fields[0].error_messages['custom'] = ['Original']
        clone = copy.deepcopy(field)
        self.assertIsNot(clone.fields[0].error_messages['custom'], field.fields[0].error_messages['custom'])

    def test_field_sets_widget_is_required(self):
        self.assertTrue(Field(required=True).widget.is_required)
        self.assertFalse(Field(required=False).widget.is_required)

    def test_cooperative_multiple_inheritance(self):
        class A:
            def __init__(self):
                self.class_a_var = True
                super().__init__()

        class ComplexField(Field, A):
            def __init__(self):
                super().__init__()

        f = ComplexField()
        self.assertTrue(f.class_a_var)

    def test_field_deepcopies_widget_instance(self):
        class CustomChoiceField(ChoiceField):
            widget = Select(attrs={'class': 'my-custom-class'})

        class TestForm(Form):
            field1 = CustomChoiceField(choices=[])
            field2 = CustomChoiceField(choices=[])

        f = TestForm()
        f.fields['field1'].choices = [('1', '1')]
        f.fields['field2'].choices = [('2', '2')]
        self.assertEqual(f.fields['field1'].widget.choices, [('1', '1')])
        self.assertEqual(f.fields['field2'].widget.choices, [('2', '2')])


class DisabledFieldTests(SimpleTestCase):
    def test_disabled_field_has_changed_always_false(self):
        disabled_field = Field(disabled=True)
        self.assertFalse(disabled_field.has_changed('x', 'y'))
