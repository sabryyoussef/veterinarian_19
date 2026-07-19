# -*- coding: utf-8 -*-
import os
import tempfile

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase

from ..models.dev_execution import (
    _assert_git_changes_allowlisted,
    _parse_git_porcelain_v1_z,
)


class TestGitPorcelainAllowlist(TransactionCase):
    def setUp(self):
        super().setUp()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = self.temporary.name
        self.addCleanup(self.temporary.cleanup)

    @staticmethod
    def _record(status, destination, source=None):
        raw = status.encode("ascii") + b" " + destination.encode("utf-8") + b"\0"
        if source is not None:
            raw += source.encode("utf-8") + b"\0"
        return raw

    def _allowed(self, raw, allowed, require_source=True):
        return _assert_git_changes_allowlisted(
            raw,
            self.root,
            allowed,
            require_rename_source=require_source,
        )

    def test_all_ordinary_status_prefixes_normalize_to_the_same_path(self):
        allowed = "tests/allowed_test_file.py"
        for status in ("??", "M ", " M", "MM", "A ", " D", "D ", "T "):
            with self.subTest(status=status):
                self.assertEqual(
                    self._allowed(self._record(status, allowed), {allowed}),
                    [allowed],
                )

    def test_ignored_record_is_parsed_when_present(self):
        allowed = "tests/allowed_test_file.py"
        records = _parse_git_porcelain_v1_z(
            self._record("!!", allowed), self.root
        )
        self.assertEqual(records[0]["status"], "!!")
        self.assertEqual(self._allowed(self._record("!!", allowed), {allowed}), [allowed])

    def test_rename_allowed_to_allowed_validates_both_paths(self):
        source = "tests/old_allowed.py"
        destination = "tests/new_allowed.py"
        raw = self._record("R ", destination, source)
        self.assertEqual(
            self._allowed(raw, {source, destination}), [destination, source]
        )

    def test_rename_disallowed_to_allowed_is_rejected(self):
        raw = self._record("R ", "tests/allowed.py", "src/disallowed.py")
        with self.assertRaises(AccessError):
            self._allowed(raw, {"tests/allowed.py"})

    def test_rename_allowed_to_disallowed_is_rejected(self):
        raw = self._record("R ", "src/disallowed.py", "tests/allowed.py")
        with self.assertRaises(AccessError):
            self._allowed(raw, {"tests/allowed.py"})

    def test_copy_record_validates_source_and_destination(self):
        source = "tests/source.py"
        destination = "tests/copy.py"
        raw = self._record("C ", destination, source)
        self.assertEqual(
            self._allowed(raw, {source, destination}), [destination, source]
        )
        with self.assertRaises(AccessError):
            self._allowed(raw, {destination})

    def test_all_unmerged_statuses_are_parsed_without_weakening_allowlist(self):
        allowed = "tests/conflict.py"
        for status in ("DD", "AU", "UD", "UA", "DU", "AA", "UU"):
            with self.subTest(status=status):
                records = _parse_git_porcelain_v1_z(
                    self._record(status, allowed), self.root
                )
                self.assertEqual(records[0]["status"], status)
                self.assertEqual(self._allowed(self._record(status, allowed), {allowed}), [allowed])

    def test_spaces_unusual_names_and_nested_paths_remain_exact(self):
        paths = (
            "tests/file with spaces.py",
            "tests/-unusual+[valid].py",
            "tests/nested/deeper/allowed.py",
        )
        raw = b"".join(self._record("??", path) for path in paths)
        self.assertEqual(self._allowed(raw, set(paths)), list(paths))

    def test_path_traversal_is_rejected_before_allowlist_check(self):
        with self.assertRaises(ValidationError):
            self._allowed(self._record("??", "../outside.py"), {"../outside.py"})
        with self.assertRaises(ValidationError):
            self._allowed(
                self._record("??", "tests/../../outside.py"),
                {"tests/../../outside.py"},
            )

    def test_absolute_path_is_rejected_before_allowlist_check(self):
        with self.assertRaises(ValidationError):
            self._allowed(self._record("??", "/tmp/outside.py"), {"/tmp/outside.py"})

    def test_symlink_escape_is_rejected(self):
        outside = tempfile.mkdtemp()
        self.addCleanup(lambda: os.rmdir(outside))
        os.symlink(outside, os.path.join(self.root, "linked"))
        with self.assertRaises(ValidationError):
            self._allowed(
                self._record("??", "linked/outside.py"), {"linked/outside.py"}
            )

    def test_malformed_unknown_and_undecodable_records_fail_closed(self):
        invalid = (
            b"?? missing-terminator",
            b"? tests/file.py\0",
            b"ZZ tests/file.py\0",
            b"?? tests/\xff.py\0",
            b"R  tests/new.py\0",
        )
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                _parse_git_porcelain_v1_z(raw, self.root)

    def test_disallowed_path_is_rejected(self):
        with self.assertRaises(AccessError):
            self._allowed(self._record("M ", "src/business.py"), {"tests/allowed.py"})

    def test_mixed_allowed_and_disallowed_changes_fail_closed(self):
        raw = b"".join(
            (
                self._record("??", "tests/allowed.py"),
                self._record(" M", "deploy/disallowed.conf"),
            )
        )
        with self.assertRaises(AccessError):
            self._allowed(raw, {"tests/allowed.py"})

    def test_dw4_first_phase5_pilot_untracked_allowlist_regression(self):
        """Regression: DW-4 compared raw ``?? `` records to path-only entries."""
        raw = b"".join(
            (
                self._record("??", "tests/__init__.py"),
                self._record("??", "tests/test_fixture_readme.py"),
            )
        )
        allowed = {"tests/__init__.py", "tests/test_fixture_readme.py"}
        self.assertEqual(
            set(self._allowed(raw, allowed)),
            allowed,
        )
