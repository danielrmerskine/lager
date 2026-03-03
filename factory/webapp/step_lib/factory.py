# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0
"""Step base class library for factory test scripts.

This module runs INSIDE the Docker container on the box. It is uploaded
alongside the test script. Backward-compatible with the legacy
``from factory import Step`` interface.

Communication protocol:
  - Events are written to stdout as ``\\x02FACTORY:`` + JSON + newline.
  - Interactive methods block on stdin for a JSON response line.
  - Regular print() output passes through as normal stdout.
"""

import json
import os
import sys
import traceback

# STX prefix used to distinguish factory protocol messages from normal output.
_PREFIX = '\x02FACTORY:'


def _send_event(event):
    """Write a factory protocol event to stdout."""
    sys.stdout.write(_PREFIX + json.dumps(event) + '\n')
    sys.stdout.flush()


def _recv_response():
    """Read one JSON response line from stdin (blocks until available)."""
    line = sys.stdin.readline()
    if not line:
        raise EOFError('stdin closed -- no response from runner')
    return json.loads(line.strip())


def get_secret(name):
    """Get a secret value from environment variables."""
    return os.environ.get(name, '')


class Step:
    """Base class for factory test steps.

    Subclass this and implement ``run(self)`` returning True (pass) or
    False (fail). Use the ``present_*`` methods to interact with the
    operator running the test.

    Class attributes (set on subclass):
        DisplayName  -- Human-readable name (default: CamelCase to sentence)
        Description  -- Step description shown in the runner UI
        Image        -- Path to an image file to display
        Link         -- URL to documentation
        StopOnFail   -- If True (default), stop the run on failure
    """

    DisplayName = None
    Description = None
    Image = None
    Link = None
    StopOnFail = True

    def __init__(self, state=None):
        self.state = state if state is not None else {}
        self._class_name = type(self).__name__

    def run(self):
        """Override this method. Return True for pass, False for fail."""
        raise NotImplementedError

    def log(self, message, file=None):
        """Log a message. Appears in the output console."""
        target = 'stderr' if file is sys.stderr else 'stdout'
        _send_event({
            'type': 'lager-log',
            'class': self._class_name,
            'file': target,
            'content': str(message),
        })

    # ------------------------------------------------------------------
    # Interactive presentation methods
    # ------------------------------------------------------------------

    def present_buttons(self, buttons):
        """Show buttons to the operator. Returns the selected value.

        Args:
            buttons: list of (label, value) tuples.
                     e.g. [('Pass', True), ('Fail', False)]
        """
        _send_event({
            'type': 'present_buttons',
            'class': self._class_name,
            'data': list(buttons),
        })
        resp = _recv_response()
        return resp.get('value')

    def present_pass_fail_buttons(self):
        """Shorthand for Pass/Fail buttons. Returns True or False."""
        return self.present_buttons([('Pass', True), ('Fail', False)])

    def present_text_input(self, prompt, size=25):
        """Show a text input. Returns the entered string."""
        _send_event({
            'type': 'present_text_input',
            'class': self._class_name,
            'data': {'prompt': prompt, 'size': size},
        })
        resp = _recv_response()
        return resp.get('value', '')

    def present_radios(self, label, choices):
        """Show radio buttons. Returns the selected value.

        Args:
            label: heading text
            choices: list of strings or (label, value) tuples
        """
        formatted = []
        for c in choices:
            if isinstance(c, (list, tuple)):
                formatted.append(list(c))
            else:
                formatted.append([str(c), c])
        _send_event({
            'type': 'present_radios',
            'class': self._class_name,
            'data': {'label': label, 'choices': formatted},
        })
        resp = _recv_response()
        return resp.get('value')

    def present_checkboxes(self, label, choices):
        """Show checkboxes. Returns list of selected values.

        Args:
            label: heading text
            choices: list of strings or (label, value) tuples
        """
        formatted = []
        for c in choices:
            if isinstance(c, (list, tuple)):
                formatted.append(list(c))
            else:
                formatted.append([str(c), c])
        _send_event({
            'type': 'present_checkboxes',
            'class': self._class_name,
            'data': {'label': label, 'choices': formatted},
        })
        resp = _recv_response()
        return resp.get('value', [])

    def present_select(self, label, choices, allow_multiple=False):
        """Show a dropdown select. Returns selected value(s).

        Args:
            label: heading text
            choices: list of strings or (label, value) tuples
            allow_multiple: if True, allows multiple selections
        """
        formatted = []
        for c in choices:
            if isinstance(c, (list, tuple)):
                formatted.append(list(c))
            else:
                formatted.append([str(c), c])
        _send_event({
            'type': 'present_select',
            'class': self._class_name,
            'data': {
                'label': label,
                'choices': formatted,
                'allow_multiple': allow_multiple,
            },
        })
        resp = _recv_response()
        return resp.get('value')

    def update_heading(self, text):
        """Update the heading text in the runner UI."""
        _send_event({
            'type': 'update_heading',
            'class': self._class_name,
            'data': {'text': text},
        })

    def present_link(self, url, text=''):
        """Show a clickable link in the runner UI."""
        _send_event({
            'type': 'present_link',
            'class': self._class_name,
            'data': {'url': url, 'text': text or url},
        })

    def present_image(self, filename):
        """Show a dynamic image in the runner UI."""
        _send_event({
            'type': 'present_image',
            'class': self._class_name,
            'data': {'filename': filename},
        })


def run(steps, finalizer_cls=None):
    """Execute a list of Step classes sequentially.

    Args:
        steps: list of Step subclasses (classes, not instances)
        finalizer_cls: optional Step class to run after all steps (even on failure)
    """
    state = {}
    success_count = 0
    failure_count = 0
    overall_pass = True
    failed_step = ''

    for step_cls in steps:
        instance = step_cls(state=state)
        class_name = step_cls.__name__

        _send_event({
            'type': 'start',
            'class': class_name,
            'name': getattr(step_cls, 'DisplayName', None) or class_name,
        })

        try:
            result = instance.run()
        except Exception:
            tb = traceback.format_exc()
            exc_type = sys.exc_info()[0]
            exc_val = sys.exc_info()[1]
            _send_event({
                'type': 'error',
                'class': class_name,
                'data': {
                    'exc_cls': exc_type.__name__ if exc_type else 'Exception',
                    'exc_str': str(exc_val),
                    'message': tb,
                },
            })
            overall_pass = False
            failure_count += 1
            if not failed_step:
                failed_step = class_name
            stop_on_fail = getattr(step_cls, 'StopOnFail', True)
            _send_event({
                'type': 'done',
                'class': class_name,
                'data': False,
                'stop_on_fail': stop_on_fail,
            })
            if stop_on_fail:
                break
            continue

        passed = bool(result)
        stop_on_fail = getattr(step_cls, 'StopOnFail', True)

        _send_event({
            'type': 'done',
            'class': class_name,
            'data': passed,
            'stop_on_fail': stop_on_fail,
        })

        if passed:
            success_count += 1
        else:
            failure_count += 1
            overall_pass = False
            if not failed_step:
                failed_step = class_name
            if stop_on_fail:
                break

        # Share state between steps
        state = instance.state

    # Run finalizer if provided
    if finalizer_cls is not None:
        try:
            finalizer = finalizer_cls(state=state)
            _send_event({
                'type': 'start',
                'class': finalizer_cls.__name__,
                'name': (getattr(finalizer_cls, 'DisplayName', None)
                         or finalizer_cls.__name__),
            })
            finalizer.run()
            _send_event({
                'type': 'done',
                'class': finalizer_cls.__name__,
                'data': True,
                'stop_on_fail': False,
            })
        except Exception:
            _send_event({
                'type': 'done',
                'class': finalizer_cls.__name__,
                'data': False,
                'stop_on_fail': False,
            })

    _send_event({
        'type': 'lager-factory-complete',
        'result': overall_pass,
        'success': success_count,
        'failure': failure_count,
        'failed_step': failed_step,
    })
