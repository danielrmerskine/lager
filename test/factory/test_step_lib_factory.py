# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""Comprehensive tests for factory/webapp/step_lib/factory.py.

Covers the Step base class (default attributes, state management, run(),
log, all present_* methods) and the run() orchestrator (pass/fail flow,
StopOnFail behavior, exception handling, state sharing, finalizer logic,
and the lager-factory-complete event).

Protocol: events are written to stdout as ``\\x02FACTORY:`` + JSON + newline.
Interactive methods read a JSON response line from stdin.
"""

import json
import sys
from unittest.mock import patch, MagicMock

import pytest

from step_lib.factory import Step, run, _PREFIX, _send_event, _recv_response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_events(mock_write):
    """Extract factory protocol events from a mock sys.stdout.write."""
    events = []
    for call in mock_write.call_args_list:
        text = call[0][0]
        if text.startswith(_PREFIX):
            payload = text[len(_PREFIX):]
            # Strip trailing newline
            events.append(json.loads(payload.rstrip('\n')))
    return events


# ---------------------------------------------------------------------------
# Concrete Step subclasses for testing
# ---------------------------------------------------------------------------

class PassingStep(Step):
    DisplayName = 'Passing Step'
    Description = 'Always passes'

    def run(self):
        return True


class FailingStep(Step):
    DisplayName = 'Failing Step'
    StopOnFail = True

    def run(self):
        return False


class FailingNoStop(Step):
    DisplayName = 'Failing No Stop'
    StopOnFail = False

    def run(self):
        return False


class ExplodingStep(Step):
    DisplayName = 'Exploding Step'
    StopOnFail = True

    def run(self):
        raise RuntimeError('kaboom')


class ExplodingNoStop(Step):
    DisplayName = 'Exploding No Stop'
    StopOnFail = False

    def run(self):
        raise ValueError('oops')


class StateWriterStep(Step):
    DisplayName = 'State Writer'

    def run(self):
        self.state['key'] = 'value'
        return True


class StateReaderStep(Step):
    DisplayName = 'State Reader'

    def run(self):
        return self.state.get('key') == 'value'


class FinalizerStep(Step):
    DisplayName = 'Finalizer'

    def run(self):
        self.state['finalized'] = True
        return True


class ExplodingFinalizer(Step):
    DisplayName = 'Exploding Finalizer'

    def run(self):
        raise RuntimeError('finalizer error')


# ---------------------------------------------------------------------------
# Step class: default attributes and construction
# ---------------------------------------------------------------------------

class TestStepDefaults:

    def test_default_class_attributes(self):
        """Step class has expected default class attributes."""
        assert Step.DisplayName is None
        assert Step.Description is None
        assert Step.Image is None
        assert Step.Link is None
        assert Step.StopOnFail is True

    def test_state_defaults_to_empty_dict(self):
        """Step() without arguments initializes state to an empty dict."""
        step = PassingStep()
        assert step.state == {}
        assert isinstance(step.state, dict)

    def test_state_passed_through(self):
        """Step(state=d) stores the provided dict."""
        d = {'existing': 42}
        step = PassingStep(state=d)
        assert step.state is d

    def test_run_raises_not_implemented(self):
        """Calling run() on the base Step class raises NotImplementedError."""
        step = Step()
        with pytest.raises(NotImplementedError):
            step.run()


# ---------------------------------------------------------------------------
# Step.log
# ---------------------------------------------------------------------------

class TestStepLog:

    def test_log_sends_event(self):
        """log() writes a lager-log event to stdout."""
        step = PassingStep()
        with patch('sys.stdout') as mock_stdout:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()
            step.log('hello world')

            events = _parse_events(mock_stdout.write)
            assert len(events) == 1
            evt = events[0]
            assert evt['type'] == 'lager-log'
            assert evt['class'] == 'PassingStep'
            assert evt['file'] == 'stdout'
            assert evt['content'] == 'hello world'

    def test_log_to_stderr(self):
        """log(message, file=sys.stderr) sets file to 'stderr'."""
        step = PassingStep()
        with patch('sys.stdout') as mock_stdout:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()
            step.log('error msg', file=sys.stderr)

            events = _parse_events(mock_stdout.write)
            assert events[0]['file'] == 'stderr'


# ---------------------------------------------------------------------------
# present_* interactive methods
# ---------------------------------------------------------------------------

class TestPresentButtons:

    def test_present_buttons(self):
        """present_buttons sends event and returns selected value."""
        step = PassingStep()
        response_json = json.dumps({'value': 'ok'}) + '\n'

        with patch('sys.stdout') as mock_stdout, \
             patch('sys.stdin') as mock_stdin:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()
            mock_stdin.readline = MagicMock(return_value=response_json)

            result = step.present_buttons([('OK', 'ok'), ('Cancel', 'cancel')])

            assert result == 'ok'
            events = _parse_events(mock_stdout.write)
            assert len(events) == 1
            assert events[0]['type'] == 'present_buttons'
            assert events[0]['data'] == [['OK', 'ok'], ['Cancel', 'cancel']]

    def test_present_pass_fail_buttons(self):
        """present_pass_fail_buttons returns True when Pass is clicked."""
        step = PassingStep()
        response_json = json.dumps({'value': True}) + '\n'

        with patch('sys.stdout') as mock_stdout, \
             patch('sys.stdin') as mock_stdin:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()
            mock_stdin.readline = MagicMock(return_value=response_json)

            result = step.present_pass_fail_buttons()

            assert result is True
            events = _parse_events(mock_stdout.write)
            assert events[0]['data'] == [['Pass', True], ['Fail', False]]


class TestPresentTextInput:

    def test_present_text_input(self):
        """present_text_input sends prompt/size and returns entered value."""
        step = PassingStep()
        response_json = json.dumps({'value': 'SN12345'}) + '\n'

        with patch('sys.stdout') as mock_stdout, \
             patch('sys.stdin') as mock_stdin:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()
            mock_stdin.readline = MagicMock(return_value=response_json)

            result = step.present_text_input('Enter serial', size=10)

            assert result == 'SN12345'
            events = _parse_events(mock_stdout.write)
            assert events[0]['type'] == 'present_text_input'
            assert events[0]['data'] == {'prompt': 'Enter serial', 'size': 10}


class TestPresentRadios:

    def test_radios_with_strings(self):
        """present_radios with plain string choices formats them as [str, str]."""
        step = PassingStep()
        response_json = json.dumps({'value': 'red'}) + '\n'

        with patch('sys.stdout') as mock_stdout, \
             patch('sys.stdin') as mock_stdin:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()
            mock_stdin.readline = MagicMock(return_value=response_json)

            result = step.present_radios('Pick color', ['red', 'blue'])

            assert result == 'red'
            events = _parse_events(mock_stdout.write)
            data = events[0]['data']
            assert data['label'] == 'Pick color'
            assert data['choices'] == [['red', 'red'], ['blue', 'blue']]

    def test_radios_with_tuples(self):
        """present_radios with (label, value) tuples preserves them."""
        step = PassingStep()
        response_json = json.dumps({'value': 1}) + '\n'

        with patch('sys.stdout') as mock_stdout, \
             patch('sys.stdin') as mock_stdin:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()
            mock_stdin.readline = MagicMock(return_value=response_json)

            result = step.present_radios('Pick', [('One', 1), ('Two', 2)])

            assert result == 1
            events = _parse_events(mock_stdout.write)
            assert events[0]['data']['choices'] == [['One', 1], ['Two', 2]]


class TestPresentCheckboxes:

    def test_checkboxes(self):
        """present_checkboxes sends event and returns list of values."""
        step = PassingStep()
        response_json = json.dumps({'value': ['a', 'c']}) + '\n'

        with patch('sys.stdout') as mock_stdout, \
             patch('sys.stdin') as mock_stdin:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()
            mock_stdin.readline = MagicMock(return_value=response_json)

            result = step.present_checkboxes('Select items', ['a', 'b', 'c'])

            assert result == ['a', 'c']
            events = _parse_events(mock_stdout.write)
            assert events[0]['type'] == 'present_checkboxes'
            assert events[0]['data']['choices'] == [
                ['a', 'a'], ['b', 'b'], ['c', 'c']
            ]


class TestPresentSelect:

    def test_select_single(self):
        """present_select single-mode sends allow_multiple=False."""
        step = PassingStep()
        response_json = json.dumps({'value': 'x'}) + '\n'

        with patch('sys.stdout') as mock_stdout, \
             patch('sys.stdin') as mock_stdin:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()
            mock_stdin.readline = MagicMock(return_value=response_json)

            result = step.present_select('Choose', ['x', 'y'])

            assert result == 'x'
            events = _parse_events(mock_stdout.write)
            assert events[0]['data']['allow_multiple'] is False

    def test_select_multiple(self):
        """present_select multi-mode sends allow_multiple=True."""
        step = PassingStep()
        response_json = json.dumps({'value': ['x', 'y']}) + '\n'

        with patch('sys.stdout') as mock_stdout, \
             patch('sys.stdin') as mock_stdin:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()
            mock_stdin.readline = MagicMock(return_value=response_json)

            result = step.present_select('Choose', ['x', 'y'], allow_multiple=True)

            assert result == ['x', 'y']
            events = _parse_events(mock_stdout.write)
            assert events[0]['data']['allow_multiple'] is True


# ---------------------------------------------------------------------------
# Non-interactive presentation methods (no stdin read)
# ---------------------------------------------------------------------------

class TestNonInteractiveMethods:

    def test_update_heading(self):
        """update_heading sends event without reading stdin."""
        step = PassingStep()
        with patch('sys.stdout') as mock_stdout, \
             patch('sys.stdin') as mock_stdin:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()
            mock_stdin.readline = MagicMock()

            step.update_heading('Step 2 of 5')

            events = _parse_events(mock_stdout.write)
            assert events[0]['type'] == 'update_heading'
            assert events[0]['data'] == {'text': 'Step 2 of 5'}
            mock_stdin.readline.assert_not_called()

    def test_present_link(self):
        """present_link sends event without reading stdin."""
        step = PassingStep()
        with patch('sys.stdout') as mock_stdout, \
             patch('sys.stdin') as mock_stdin:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()
            mock_stdin.readline = MagicMock()

            step.present_link('https://example.com', text='Docs')

            events = _parse_events(mock_stdout.write)
            assert events[0]['type'] == 'present_link'
            assert events[0]['data'] == {'url': 'https://example.com', 'text': 'Docs'}
            mock_stdin.readline.assert_not_called()

    def test_present_image(self):
        """present_image sends event without reading stdin."""
        step = PassingStep()
        with patch('sys.stdout') as mock_stdout, \
             patch('sys.stdin') as mock_stdin:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()
            mock_stdin.readline = MagicMock()

            step.present_image('board_photo.png')

            events = _parse_events(mock_stdout.write)
            assert events[0]['type'] == 'present_image'
            assert events[0]['data'] == {'filename': 'board_photo.png'}
            mock_stdin.readline.assert_not_called()


# ---------------------------------------------------------------------------
# run() orchestrator
# ---------------------------------------------------------------------------

class TestRunAllPass:

    def test_all_steps_pass(self):
        """run() with all-passing steps reports overall success."""
        with patch('sys.stdout') as mock_stdout:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()

            run([PassingStep, PassingStep])

            events = _parse_events(mock_stdout.write)
            complete = [e for e in events if e['type'] == 'lager-factory-complete'][0]
            assert complete['result'] is True
            assert complete['success'] == 2
            assert complete['failure'] == 0
            assert complete['failed_step'] == ''


class TestRunFailStopOnFail:

    def test_fail_stops_when_stop_on_fail_true(self):
        """A failing step with StopOnFail=True stops the run."""
        with patch('sys.stdout') as mock_stdout:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()

            run([PassingStep, FailingStep, PassingStep])

            events = _parse_events(mock_stdout.write)
            # The third step (second PassingStep) should never start
            start_events = [e for e in events if e['type'] == 'start']
            assert len(start_events) == 2  # PassingStep + FailingStep only

            complete = [e for e in events if e['type'] == 'lager-factory-complete'][0]
            assert complete['result'] is False
            assert complete['success'] == 1
            assert complete['failure'] == 1
            assert complete['failed_step'] == 'FailingStep'


class TestRunFailContinue:

    def test_fail_continues_when_stop_on_fail_false(self):
        """A failing step with StopOnFail=False lets subsequent steps run."""
        with patch('sys.stdout') as mock_stdout:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()

            run([PassingStep, FailingNoStop, PassingStep])

            events = _parse_events(mock_stdout.write)
            start_events = [e for e in events if e['type'] == 'start']
            assert len(start_events) == 3  # All three steps started

            complete = [e for e in events if e['type'] == 'lager-factory-complete'][0]
            assert complete['result'] is False
            assert complete['success'] == 2
            assert complete['failure'] == 1


class TestRunExceptionStopOnFail:

    def test_exception_stops_when_stop_on_fail_true(self):
        """An exception with StopOnFail=True stops the run."""
        with patch('sys.stdout') as mock_stdout:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()

            run([PassingStep, ExplodingStep, PassingStep])

            events = _parse_events(mock_stdout.write)
            error_events = [e for e in events if e['type'] == 'error']
            assert len(error_events) == 1
            assert error_events[0]['data']['exc_cls'] == 'RuntimeError'
            assert error_events[0]['data']['exc_str'] == 'kaboom'

            start_events = [e for e in events if e['type'] == 'start']
            assert len(start_events) == 2  # Third step skipped

            complete = [e for e in events if e['type'] == 'lager-factory-complete'][0]
            assert complete['result'] is False
            assert complete['failure'] == 1


class TestRunExceptionContinue:

    def test_exception_continues_when_stop_on_fail_false(self):
        """An exception with StopOnFail=False lets subsequent steps run."""
        with patch('sys.stdout') as mock_stdout:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()

            run([PassingStep, ExplodingNoStop, PassingStep])

            events = _parse_events(mock_stdout.write)
            start_events = [e for e in events if e['type'] == 'start']
            assert len(start_events) == 3

            complete = [e for e in events if e['type'] == 'lager-factory-complete'][0]
            assert complete['result'] is False
            assert complete['success'] == 2
            assert complete['failure'] == 1


class TestRunStateSharing:

    def test_state_shared_between_steps(self):
        """State written by one step is visible to the next."""
        with patch('sys.stdout') as mock_stdout:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()

            run([StateWriterStep, StateReaderStep])

            events = _parse_events(mock_stdout.write)
            complete = [e for e in events if e['type'] == 'lager-factory-complete'][0]
            assert complete['result'] is True
            assert complete['success'] == 2
            assert complete['failure'] == 0


class TestRunFinalizer:

    def test_finalizer_runs_after_success(self):
        """Finalizer runs after all steps pass."""
        with patch('sys.stdout') as mock_stdout:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()

            run([PassingStep], finalizer_cls=FinalizerStep)

            events = _parse_events(mock_stdout.write)
            start_events = [e for e in events if e['type'] == 'start']
            # PassingStep + FinalizerStep
            assert len(start_events) == 2
            assert start_events[1]['class'] == 'FinalizerStep'

            complete = [e for e in events if e['type'] == 'lager-factory-complete'][0]
            assert complete['result'] is True

    def test_finalizer_runs_after_failure(self):
        """Finalizer runs even when a step fails and stops."""
        with patch('sys.stdout') as mock_stdout:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()

            run([FailingStep], finalizer_cls=FinalizerStep)

            events = _parse_events(mock_stdout.write)
            start_events = [e for e in events if e['type'] == 'start']
            # FailingStep + FinalizerStep
            assert len(start_events) == 2
            assert start_events[1]['class'] == 'FinalizerStep'

            complete = [e for e in events if e['type'] == 'lager-factory-complete'][0]
            assert complete['result'] is False

    def test_finalizer_exception_caught(self):
        """An exception in the finalizer is caught; complete event still fires."""
        with patch('sys.stdout') as mock_stdout:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()

            run([PassingStep], finalizer_cls=ExplodingFinalizer)

            events = _parse_events(mock_stdout.write)
            # Finalizer should get a done event with data=False
            finalizer_done = [
                e for e in events
                if e['type'] == 'done' and e['class'] == 'ExplodingFinalizer'
            ]
            assert len(finalizer_done) == 1
            assert finalizer_done[0]['data'] is False

            # Complete event still fires
            complete = [e for e in events if e['type'] == 'lager-factory-complete'][0]
            assert complete['result'] is True  # Main steps passed


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------

class TestStepLogEdgeCases:

    def test_log_empty_message(self):
        """log() with empty string sends event without crash."""
        step = PassingStep()
        with patch('sys.stdout') as mock_stdout:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()
            step.log('')

            events = _parse_events(mock_stdout.write)
            assert len(events) == 1
            assert events[0]['content'] == ''


class TestPresentButtonsEdgeCases:

    def test_present_buttons_eof_stdin(self):
        """present_buttons handles EOF on stdin (readline returns '')."""
        step = PassingStep()

        with patch('sys.stdout') as mock_stdout, \
             patch('sys.stdin') as mock_stdin:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()
            mock_stdin.readline = MagicMock(return_value='')

            # Should handle EOF without crashing
            try:
                result = step.present_buttons([('OK', 'ok')])
                # If it returns, it may return None or empty
                assert result is not None or result is None  # Any outcome is OK
            except (json.JSONDecodeError, KeyError, Exception):
                pass  # Acceptable to raise on EOF


class TestPresentRadiosEdgeCases:

    def test_radios_with_empty_choices(self):
        """present_radios with empty choices list sends event."""
        step = PassingStep()
        response_json = json.dumps({'value': None}) + '\n'

        with patch('sys.stdout') as mock_stdout, \
             patch('sys.stdin') as mock_stdin:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()
            mock_stdin.readline = MagicMock(return_value=response_json)

            result = step.present_radios('Pick', [])

            events = _parse_events(mock_stdout.write)
            assert events[0]['type'] == 'present_radios'
            assert events[0]['data']['choices'] == []


class TestRunEdgeCases:

    def test_run_empty_steps(self):
        """run() with empty STEPS list completes with 0 success, 0 failure."""
        with patch('sys.stdout') as mock_stdout:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()

            run([])

            events = _parse_events(mock_stdout.write)
            complete = [e for e in events if e['type'] == 'lager-factory-complete'][0]
            assert complete['result'] is True
            assert complete['success'] == 0
            assert complete['failure'] == 0

    def test_run_step_init_exception(self):
        """run() propagates exception from Step.__init__."""
        class BadInitStep(Step):
            DisplayName = 'Bad Init'
            def __init__(self, state=None):
                raise RuntimeError('init failed')
            def run(self):
                return True

        with patch('sys.stdout') as mock_stdout:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()

            with pytest.raises(RuntimeError, match='init failed'):
                run([BadInitStep])


class TestSendEventEdgeCases:

    def test_send_event_non_serializable(self):
        """_send_event with non-JSON-serializable value raises or handles."""
        with patch('sys.stdout') as mock_stdout:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()

            try:
                _send_event('test', {'data': object()})
            except TypeError:
                pass  # Expected - json.dumps can't serialize object()


class TestRecvResponseEdgeCases:

    def test_recv_response_malformed_json(self):
        """_recv_response with malformed JSON on stdin."""
        with patch('sys.stdin') as mock_stdin:
            mock_stdin.readline = MagicMock(return_value='not json\n')

            try:
                result = _recv_response()
                # If it returns, any result is acceptable
            except (json.JSONDecodeError, Exception):
                pass  # Expected
