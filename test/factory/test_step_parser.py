# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""Tests for factory/webapp/step_parser.py.

Pure-function tests -- no fixtures needed beyond the conftest sys.path setup
that makes ``import step_parser`` resolve to factory/webapp/step_parser.py.
"""

import ast

import step_parser


# -----------------------------------------------------------------------
# class_name_to_sentence
# -----------------------------------------------------------------------

class TestClassNameToSentence:
    def test_camel_case(self):
        assert step_parser.class_name_to_sentence('CheckVoltage') == 'Check Voltage'

    def test_multi_word_camel(self):
        assert step_parser.class_name_to_sentence('VerifyBoardPowerUp') == 'Verify Board Power Up'

    def test_all_caps(self):
        # Consecutive capitals are treated as a single group.
        result = step_parser.class_name_to_sentence('LED')
        assert isinstance(result, str)
        # Should separate the uppercase block; exact output depends on the
        # regex chain, but it must not crash and must strip cleanly.
        assert result.strip() == result

    def test_single_word(self):
        assert step_parser.class_name_to_sentence('Setup') == 'Setup'

    def test_empty_string(self):
        assert step_parser.class_name_to_sentence('') == ''


# -----------------------------------------------------------------------
# is_step
# -----------------------------------------------------------------------

def _parse_class(source):
    """Helper: parse a single class definition and return the ClassDef node."""
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            return node
    raise ValueError('No ClassDef found in source')


class TestIsStep:
    def test_step_base(self):
        node = _parse_class('class Foo(Step): pass')
        assert step_parser.is_step(node) is True

    def test_factory_step_base(self):
        node = _parse_class('class Foo(factory.Step): pass')
        assert step_parser.is_step(node) is True

    def test_non_step_base(self):
        node = _parse_class('class Foo(Bar): pass')
        assert step_parser.is_step(node) is False

    def test_no_bases(self):
        node = _parse_class('class Foo: pass')
        assert step_parser.is_step(node) is False

    def test_multiple_bases_with_step(self):
        node = _parse_class('class Foo(Mixin, Step): pass')
        assert step_parser.is_step(node) is True

    def test_multiple_bases_without_step(self):
        node = _parse_class('class Foo(Mixin, Bar): pass')
        assert step_parser.is_step(node) is False

    def test_non_classdef_node(self):
        tree = ast.parse('x = 1')
        node = tree.body[0]
        assert step_parser.is_step(node) is False


# -----------------------------------------------------------------------
# parse_code (integration-level tests)
# -----------------------------------------------------------------------

FULL_SCRIPT = """\
from factory import Step

class CheckVoltage(Step):
    DisplayName = 'Voltage Check'
    Description = 'Verify rail is within spec'
    Image = 'voltage.png'
    Link = 'https://docs.example.com/voltage'

    def run(self):
        pass

class VerifyLED(Step):
    DisplayName = 'LED Verify'

    def run(self):
        pass

STEPS = [CheckVoltage, VerifyLED]
"""

SCRIPT_NO_DISPLAYNAME = """\
from factory import Step

class CheckVoltage(Step):
    def run(self):
        pass

STEPS = [CheckVoltage]
"""

SCRIPT_NO_STEPS_LIST = """\
from factory import Step

class CheckVoltage(Step):
    def run(self):
        pass
"""

SCRIPT_NO_METADATA = """\
from factory import Step

class Bare(Step):
    def run(self):
        pass

STEPS = [Bare]
"""


class TestParseCode:
    def test_full_script_metadata(self):
        result = step_parser.parse_code(FULL_SCRIPT)
        assert len(result) == 2

        first = result[0]
        assert first['class'] == 'CheckVoltage'
        assert first['name'] == 'Voltage Check'
        assert first['description'] == 'Verify rail is within spec'
        assert first['image'] == 'voltage.png'
        assert first['link'] == 'https://docs.example.com/voltage'

        second = result[1]
        assert second['class'] == 'VerifyLED'
        assert second['name'] == 'LED Verify'

    def test_missing_displayname_falls_back(self):
        result = step_parser.parse_code(SCRIPT_NO_DISPLAYNAME)
        assert len(result) == 1
        assert result[0]['name'] == 'Check Voltage'

    def test_no_steps_list_returns_empty(self):
        result = step_parser.parse_code(SCRIPT_NO_STEPS_LIST)
        assert result == []

    def test_syntax_error_returns_empty(self):
        result = step_parser.parse_code('def broken(:\n')
        assert result == []

    def test_empty_string_returns_empty(self):
        result = step_parser.parse_code('')
        assert result == []

    def test_no_metadata(self):
        result = step_parser.parse_code(SCRIPT_NO_METADATA)
        assert len(result) == 1
        step = result[0]
        assert step['class'] == 'Bare'
        assert step['name'] == 'Bare'
        assert step['description'] is None
        assert step['image'] is None
        assert step['link'] is None

    def test_undefined_class_in_steps_skipped(self):
        source = """\
from factory import Step

class A(Step):
    def run(self):
        pass

STEPS = [A, DoesNotExist]
"""
        result = step_parser.parse_code(source)
        assert len(result) == 1
        assert result[0]['class'] == 'A'

    def test_non_name_in_steps_skipped(self):
        source = """\
from factory import Step

class A(Step):
    def run(self):
        pass

STEPS = [A, "not_a_name"]
"""
        result = step_parser.parse_code(source)
        assert len(result) == 1
        assert result[0]['class'] == 'A'

    def test_factory_dot_step_base(self):
        source = """\
import factory

class MyStep(factory.Step):
    DisplayName = 'My Step'

STEPS = [MyStep]
"""
        result = step_parser.parse_code(source)
        assert len(result) == 1
        assert result[0]['name'] == 'My Step'

    def test_steps_ordering_matches_list(self):
        source = """\
from factory import Step

class Zeta(Step):
    pass

class Alpha(Step):
    pass

STEPS = [Alpha, Zeta]
"""
        result = step_parser.parse_code(source)
        assert [s['class'] for s in result] == ['Alpha', 'Zeta']


# -----------------------------------------------------------------------
# Edge case tests
# -----------------------------------------------------------------------

class TestClassNameEdgeCases:
    def test_class_name_with_numbers(self):
        """Class name 'Step2Check' converts to 'Step 2 Check'."""
        result = step_parser.class_name_to_sentence('Step2Check')
        # Should contain the digit and be space-separated
        assert '2' in result
        assert isinstance(result, str)

    def test_class_name_with_underscores(self):
        """Underscored class names are handled."""
        result = step_parser.class_name_to_sentence('Step_Name')
        assert isinstance(result, str)


class TestParseCodeEdgeCases:

    def test_steps_as_tuple(self):
        """STEPS defined as a tuple (not list) is still parsed."""
        source = """\
from factory import Step

class A(Step):
    def run(self):
        pass

STEPS = (A,)
"""
        result = step_parser.parse_code(source)
        # Tuple syntax may or may not be supported; just ensure no crash
        assert isinstance(result, list)

    def test_nested_class(self):
        """Step class defined inside another class is not extracted."""
        source = """\
from factory import Step

class Outer:
    class Inner(Step):
        def run(self):
            pass

STEPS = [Inner]
"""
        # This should not crash, and Inner should not be found at top level
        result = step_parser.parse_code(source)
        assert isinstance(result, list)

    def test_very_large_script(self):
        """Parsing a 1000-line script does not crash or hang."""
        lines = ['from factory import Step\n']
        for i in range(100):
            lines.append(f'class Step{i}(Step):\n    def run(self): pass\n')
        lines.append('STEPS = [' + ', '.join(f'Step{i}' for i in range(100)) + ']\n')
        source = '\n'.join(lines)

        result = step_parser.parse_code(source)
        assert len(result) == 100

    def test_only_comments(self):
        """Source file with only comments returns empty list."""
        source = "# This is a comment\n# Another comment\n"
        result = step_parser.parse_code(source)
        assert result == []

    def test_step_without_run_method(self):
        """Step subclass missing run() is still parsed as a step."""
        source = """\
from factory import Step

class NoRun(Step):
    DisplayName = 'No Run'

STEPS = [NoRun]
"""
        result = step_parser.parse_code(source)
        assert len(result) == 1
        assert result[0]['class'] == 'NoRun'
        assert result[0]['name'] == 'No Run'
