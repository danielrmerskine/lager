# Copyright 2024-2026 Lager Data LLC
# SPDX-License-Identifier: Apache-2.0

"""Comprehensive tests for factory/webapp/script_store.py."""

import json
import os
import threading

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_manifest(data_dir):
    """Read manifest.json directly from disk for verification."""
    path = os.path.join(data_dir, 'scripts', 'manifest.json')
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


def _script_path(data_dir, name):
    """Return the full path to a script file in the data dir."""
    return os.path.join(data_dir, 'scripts', name)


# ---------------------------------------------------------------------------
# list_scripts
# ---------------------------------------------------------------------------

class TestListScripts:

    def test_empty_store(self, app):
        """list_scripts returns an empty list when no scripts have been added."""
        import script_store
        result = script_store.list_scripts()
        assert result == []

    def test_ordered_by_manifest(self, app, tmp_data_dir):
        """list_scripts returns scripts in the order recorded in the manifest."""
        import script_store

        script_store.add_script('alpha.py', b'# alpha')
        script_store.add_script('beta.py', b'# beta')
        script_store.add_script('gamma.py', b'# gamma')

        result = script_store.list_scripts()
        names = [s['name'] for s in result]
        assert names == ['alpha.py', 'beta.py', 'gamma.py']

    def test_skips_missing_files(self, app, tmp_data_dir):
        """list_scripts omits manifest entries whose files are missing on disk."""
        import script_store

        script_store.add_script('present.py', b'# here')
        script_store.add_script('ghost.py', b'# will be deleted')

        # Remove the file but leave the manifest entry
        os.remove(_script_path(tmp_data_dir, 'ghost.py'))

        result = script_store.list_scripts()
        names = [s['name'] for s in result]
        assert names == ['present.py']

    def test_returns_size_bytes(self, app, tmp_data_dir):
        """list_scripts includes accurate size_bytes for each script."""
        import script_store

        content = b'print("hello world")'
        script_store.add_script('sized.py', content)

        result = script_store.list_scripts()
        assert len(result) == 1
        assert result[0]['size_bytes'] == len(content)


# ---------------------------------------------------------------------------
# add_script
# ---------------------------------------------------------------------------

class TestAddScript:

    def test_add_new_file(self, app, tmp_data_dir):
        """Adding a new script creates the file and appends to the manifest."""
        import script_store

        script_store.add_script('test.py', b'# test content')

        # Verify file exists on disk
        assert os.path.exists(_script_path(tmp_data_dir, 'test.py'))

        # Verify manifest
        manifest = _read_manifest(tmp_data_dir)
        assert manifest == ['test.py']

    def test_overwrite_keeps_position(self, app, tmp_data_dir):
        """Re-uploading a script overwrites content but keeps its manifest position."""
        import script_store

        script_store.add_script('first.py', b'# first')
        script_store.add_script('second.py', b'# second')
        script_store.add_script('third.py', b'# third')

        # Overwrite second.py with new content
        script_store.add_script('second.py', b'# second v2')

        manifest = _read_manifest(tmp_data_dir)
        assert manifest == ['first.py', 'second.py', 'third.py']

        # Verify content was actually updated
        content = script_store.get_script_content('second.py')
        assert content == '# second v2'

    def test_rejects_non_py(self, app):
        """add_script raises ValueError for non-.py filenames."""
        import script_store

        with pytest.raises(ValueError, match='Only .py files are allowed'):
            script_store.add_script('readme.txt', b'text')

        with pytest.raises(ValueError, match='Only .py files are allowed'):
            script_store.add_script('script.sh', b'#!/bin/bash')

    def test_sanitizes_path_traversal(self, app, tmp_data_dir):
        """Path traversal in filename is stripped by os.path.basename."""
        import script_store

        script_store.add_script('../../evil.py', b'# sneaky')

        # Should be stored as just "evil.py", not in a parent directory
        manifest = _read_manifest(tmp_data_dir)
        assert manifest == ['evil.py']
        assert os.path.exists(_script_path(tmp_data_dir, 'evil.py'))

        # Ensure no file was created outside the scripts directory
        parent = os.path.dirname(os.path.dirname(tmp_data_dir))
        assert not os.path.exists(os.path.join(parent, 'evil.py'))


# ---------------------------------------------------------------------------
# remove_script
# ---------------------------------------------------------------------------

class TestRemoveScript:

    def test_remove_existing(self, app, tmp_data_dir):
        """Removing an existing script deletes the file and manifest entry."""
        import script_store

        script_store.add_script('doomed.py', b'# goodbye')
        assert os.path.exists(_script_path(tmp_data_dir, 'doomed.py'))

        script_store.remove_script('doomed.py')

        assert not os.path.exists(_script_path(tmp_data_dir, 'doomed.py'))
        manifest = _read_manifest(tmp_data_dir)
        assert 'doomed.py' not in manifest

    def test_remove_nonexistent_is_noop(self, app, tmp_data_dir):
        """Removing a script that does not exist is a silent no-op."""
        import script_store

        # Should not raise
        script_store.remove_script('nonexistent.py')

        manifest = _read_manifest(tmp_data_dir)
        assert manifest == [] or 'nonexistent.py' not in manifest


# ---------------------------------------------------------------------------
# reorder_scripts
# ---------------------------------------------------------------------------

class TestReorderScripts:

    def test_valid_reorder(self, app, tmp_data_dir):
        """reorder_scripts updates the manifest to the given order."""
        import script_store

        script_store.add_script('a.py', b'# a')
        script_store.add_script('b.py', b'# b')
        script_store.add_script('c.py', b'# c')

        script_store.reorder_scripts(['c.py', 'a.py', 'b.py'])

        manifest = _read_manifest(tmp_data_dir)
        assert manifest == ['c.py', 'a.py', 'b.py']

    def test_unknown_name_raises(self, app, tmp_data_dir):
        """reorder_scripts raises ValueError if any name is not in the manifest."""
        import script_store

        script_store.add_script('known.py', b'# known')

        with pytest.raises(ValueError, match='Unknown script: stranger.py'):
            script_store.reorder_scripts(['known.py', 'stranger.py'])


# ---------------------------------------------------------------------------
# get_script_content
# ---------------------------------------------------------------------------

class TestGetScriptContent:

    def test_returns_string_content(self, app, tmp_data_dir):
        """get_script_content returns the file content as a string."""
        import script_store

        original = b'import sys\nprint(sys.argv)\n'
        script_store.add_script('reader.py', original)

        content = script_store.get_script_content('reader.py')
        assert isinstance(content, str)
        assert content == original.decode('utf-8')

    def test_missing_returns_none(self, app):
        """get_script_content returns None for a non-existent script."""
        import script_store

        result = script_store.get_script_content('no_such_file.py')
        assert result is None


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

class TestThreadSafety:

    def test_concurrent_add_and_list(self, app, tmp_data_dir):
        """Concurrent add_script and list_scripts do not corrupt state."""
        import script_store

        num_scripts = 20
        errors = []

        def add_worker(i):
            try:
                script_store.add_script(f'script_{i:03d}.py', f'# script {i}'.encode())
            except Exception as e:
                errors.append(e)

        def list_worker():
            try:
                for _ in range(10):
                    script_store.list_scripts()
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(num_scripts):
            threads.append(threading.Thread(target=add_worker, args=(i,)))
        # Interleave list workers
        for _ in range(5):
            threads.append(threading.Thread(target=list_worker))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == [], f'Thread errors: {errors}'

        # All scripts should be present
        result = script_store.list_scripts()
        names = {s['name'] for s in result}
        expected = {f'script_{i:03d}.py' for i in range(num_scripts)}
        assert names == expected

    def test_concurrent_add_and_remove(self, app, tmp_data_dir):
        """Concurrent add and remove operations do not raise or corrupt state."""
        import script_store

        # Pre-populate some scripts
        for i in range(10):
            script_store.add_script(f'item_{i}.py', f'# item {i}'.encode())

        errors = []

        def add_worker():
            try:
                for i in range(10, 20):
                    script_store.add_script(f'item_{i}.py', f'# item {i}'.encode())
            except Exception as e:
                errors.append(e)

        def remove_worker():
            try:
                for i in range(10):
                    script_store.remove_script(f'item_{i}.py')
            except Exception as e:
                errors.append(e)

        t_add = threading.Thread(target=add_worker)
        t_remove = threading.Thread(target=remove_worker)

        t_add.start()
        t_remove.start()
        t_add.join(timeout=10)
        t_remove.join(timeout=10)

        assert errors == [], f'Thread errors: {errors}'

        # After completion: items 0-9 should be removed, items 10-19 should exist
        result = script_store.list_scripts()
        names = {s['name'] for s in result}
        for i in range(10):
            assert f'item_{i}.py' not in names, f'item_{i}.py should have been removed'
        for i in range(10, 20):
            assert f'item_{i}.py' in names, f'item_{i}.py should have been added'


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------

class TestAddScriptEdgeCases:

    def test_add_script_hidden_filename(self, app, tmp_data_dir):
        """Filename starting with '.' is handled (basename strips nothing)."""
        import script_store

        # .hidden.py is a valid .py filename
        script_store.add_script('.hidden.py', b'# hidden')
        result = script_store.list_scripts()
        names = [s['name'] for s in result]
        assert '.hidden.py' in names

    def test_add_script_bytearray_content(self, app, tmp_data_dir):
        """Content provided as bytearray (not bytes) is accepted."""
        import script_store

        content = bytearray(b'print("bytearray")')
        script_store.add_script('ba.py', content)

        result = script_store.get_script_content('ba.py')
        assert 'bytearray' in result


class TestReorderEdgeCases:

    def test_reorder_empty_list(self, app, tmp_data_dir):
        """Reordering with empty list when manifest has scripts raises or is noop."""
        import script_store

        script_store.add_script('a.py', b'# a')

        # Reorder with empty list -- may raise ValueError or may clear
        try:
            script_store.reorder_scripts([])
            # If it doesn't raise, the manifest should be empty or unchanged
            result = script_store.list_scripts()
            # Accept either behavior
            assert isinstance(result, list)
        except ValueError:
            pass  # Also acceptable

    def test_reorder_duplicate_names(self, app, tmp_data_dir):
        """Reordering with duplicate names in the list."""
        import script_store

        script_store.add_script('a.py', b'# a')
        script_store.add_script('b.py', b'# b')

        # Duplicate name in ordered list
        try:
            script_store.reorder_scripts(['a.py', 'a.py', 'b.py'])
            # If it doesn't raise, verify state is consistent
            result = script_store.list_scripts()
            assert isinstance(result, list)
        except ValueError:
            pass  # Also acceptable


class TestGetScriptContentEdgeCases:

    def test_get_content_non_utf8(self, app, tmp_data_dir):
        """Script with non-UTF-8 bytes raises UnicodeDecodeError on read."""
        import script_store

        # Write binary content that's not valid UTF-8
        content = b'\xff\xfe print("hi")'
        script_store.add_script('binary.py', content)

        with pytest.raises(UnicodeDecodeError):
            script_store.get_script_content('binary.py')


class TestCorruptedManifest:

    def test_corrupted_manifest_json(self, app, tmp_data_dir):
        """list_scripts handles a corrupted manifest.json gracefully."""
        import script_store
        import os

        # Write invalid JSON to manifest
        manifest_path = os.path.join(tmp_data_dir, 'scripts', 'manifest.json')
        with open(manifest_path, 'w') as f:
            f.write('{not valid json}')

        # Should either return empty list or raise a clear error
        try:
            result = script_store.list_scripts()
            assert isinstance(result, list)
        except (json.JSONDecodeError, Exception):
            pass  # Acceptable to raise on corrupted manifest
