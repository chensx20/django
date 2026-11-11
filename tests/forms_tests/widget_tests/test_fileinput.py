from django.forms import FileInput

from .base import WidgetTest


class FileInputTest(WidgetTest):
    widget = FileInput()

    def test_render(self):
        """
        FileInput widgets never render the value attribute. The old value
        isn't useful if a form is updated or an error occurred.
        """
        self.check_html(self.widget, 'email', 'test@example.com', html='<input type="file" name="email">')
        self.check_html(self.widget, 'email', '', html='<input type="file" name="email">')
        self.check_html(self.widget, 'email', None, html='<input type="file" name="email">')

    def test_value_omitted_from_data(self):
        self.assertIs(self.widget.value_omitted_from_data({}, {}, 'field'), True)
        self.assertIs(self.widget.value_omitted_from_data({}, {'field': 'value'}, 'field'), False)

    def test_use_required_attribute(self):
        for initial, expected in ((None, True), ('', True), ('resume.txt', False), (object(), False)):
            with self.subTest(initial=initial):
                self.assertIs(self.widget.use_required_attribute(initial), expected)

    def test_use_required_attribute_hidden(self):
        class HiddenFileInput(FileInput):
            input_type = 'hidden'

        widget = HiddenFileInput()
        for initial in (None, '', 'resume.txt'):
            with self.subTest(initial=initial):
                self.assertIs(widget.use_required_attribute(initial), False)
