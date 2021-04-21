"""Test for Word cloud Xmodule functional logic."""

import json
from unittest import mock

from django.test import TestCase
from django.test.utils import override_settings
from fs.memoryfs import MemoryFS
from lxml import etree
from opaque_keys.edx.locator import BlockUsageLocator, CourseLocator
from webob.multidict import MultiDict
from xblock.field_data import DictFieldData

from xmodule.word_cloud_module import WordCloudBlock, toggle_mobile_support
from . import get_test_descriptor_system, get_test_system


class WordCloudBlockTest(TestCase):
    """
    Logic tests for Word Cloud XBlock.
    """

    raw_field_data = {
        'all_words': {'cat': 10, 'dog': 5, 'mom': 1, 'dad': 2},
        'top_words': {'cat': 10, 'dog': 5, 'dad': 2},
        'submitted': False,
        'display_name': 'Word Cloud Block',
        'instructions': 'Enter some random words that comes to your mind'
    }

    def test_xml_import_export_cycle(self):
        """
        Test the import export cycle.
        """

        runtime = get_test_descriptor_system()
        runtime.export_fs = MemoryFS()

        original_xml = (
            '<word_cloud display_name="Favorite Fruits" display_student_percents="false" '
            'instructions="What are your favorite fruits?" num_inputs="3" num_top_words="100"/>\n'
        )

        olx_element = etree.fromstring(original_xml)
        id_generator = mock.Mock()
        block = WordCloudBlock.parse_xml(olx_element, runtime, None, id_generator)
        block.location = BlockUsageLocator(
            CourseLocator('org', 'course', 'run', branch='revision'), 'word_cloud', 'block_id'
        )

        assert block.display_name == 'Favorite Fruits'
        assert not block.display_student_percents
        assert block.instructions == 'What are your favorite fruits?'
        assert block.num_inputs == 3
        assert block.num_top_words == 100

        node = etree.Element("unknown_root")
        # This will export the olx to a separate file.
        block.add_xml_to_node(node)
        with runtime.export_fs.open('word_cloud/block_id.xml') as f:
            exported_xml = f.read()

        assert exported_xml == original_xml

    def test_bad_ajax_request(self):
        """
        Make sure that answer for incorrect request is error json.
        """

        module_system = get_test_system()
        block = WordCloudBlock(module_system, DictFieldData(self.raw_field_data), mock.Mock())

        response = json.loads(block.handle_ajax('bad_dispatch', {}))
        self.assertDictEqual(response, {
            'status': 'fail',
            'error': 'Unknown Command!'
        })

    def test_good_ajax_request(self):
        """
        Make sure that ajax request works correctly.
        """

        module_system = get_test_system()
        block = WordCloudBlock(module_system, DictFieldData(self.raw_field_data), mock.Mock())

        post_data = MultiDict(('student_words[]', word) for word in ['cat', 'cat', 'dog', 'sun'])
        response = json.loads(block.handle_ajax('submit', post_data))
        assert response['status'] == 'success'
        assert response['submitted'] is True
        assert response['total_count'] == 22
        self.assertDictEqual(
            response['student_words'],
            {'sun': 1, 'dog': 6, 'cat': 12}
        )

        self.assertListEqual(
            response['top_words'],
            [{'text': 'cat', 'size': 12, 'percent': 55.0},
             {'text': 'dad', 'size': 2, 'percent': 9.0},
             {'text': 'dog', 'size': 6, 'percent': 27.0},
             {'text': 'mom', 'size': 1, 'percent': 5.0},
             {'text': 'sun', 'size': 1, 'percent': 4.0}]
        )

        assert 100.0 == sum(i['percent'] for i in response['top_words'])

    def test_indexibility(self):
        """
        Test indexibility of Word Cloud
        """

        module_system = get_test_system()
        block = WordCloudBlock(module_system, DictFieldData(self.raw_field_data), mock.Mock())
        assert block.index_dictionary() ==\
               {'content_type': 'Word Cloud',
                'content': {'display_name': 'Word Cloud Block',
                            'instructions': 'Enter some random words that comes to your mind'}}

    @mock.patch('xblock.core.XBlock.supports')
    def test_mobile_supports_enabled(self, xblock_supports_mock):
        """
        Make sure that answer for incorrect request is error json.
        """
        with override_settings(FEATURES=dict(ENABLE_WORD_CLOUD_MOBILE_SUPPORT=True)):
            xblock_decorator = mock.Mock()
            xblock_supports_mock.return_value = xblock_decorator
            some_function = mock.Mock()
            toggle_mobile_support(some_function)

            xblock_supports_mock.assert_called_once_with('multi_device')
            xblock_decorator.assert_called_once_with(some_function)

    @mock.patch('xblock.core.XBlock.supports')
    def test_mobile_supports_disabled(self, xblock_supports_mock):
        """
        Make sure that answer for incorrect request is error json.
        """
        some_function = mock.Mock()
        toggle_mobile_support(some_function)

        xblock_supports_mock.assert_not_called()
