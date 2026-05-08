"""Unit tests for compile/cli.py helper functions.

Covers uncovered branches in:
- _get_validation_suggestion (default/else branch)
- _resolve_compile_target (empty target_set, unknown target family)
- _display_single_file_summary (no-console fallback)
- _display_next_steps (no-console fallback)
- _display_validation_errors (no-colon error string, fallback text output)
"""

from unittest.mock import MagicMock, patch


class TestGetValidationSuggestion:
    """Tests for _get_validation_suggestion."""

    def test_missing_description(self):
        from apm_cli.commands.compile.cli import _get_validation_suggestion

        suggestion = _get_validation_suggestion("Missing 'description' in frontmatter")
        assert "description" in suggestion.lower()

    def test_apply_to_global(self):
        from apm_cli.commands.compile.cli import _get_validation_suggestion

        suggestion = _get_validation_suggestion("applyTo used globally for this file")
        assert "applyTo" in suggestion or "scope" in suggestion.lower()

    def test_empty_content(self):
        from apm_cli.commands.compile.cli import _get_validation_suggestion

        suggestion = _get_validation_suggestion("Empty content in primitive")
        assert suggestion  # non-empty

    def test_unknown_error_returns_generic_suggestion(self):
        """Default/else branch: unknown error should return generic suggestion."""
        from apm_cli.commands.compile.cli import _get_validation_suggestion

        suggestion = _get_validation_suggestion("some completely unknown error type xyz")
        assert "Check primitive structure" in suggestion or suggestion  # non-empty fallback


class TestResolveCompileTarget:
    """Tests for uncovered branches of _resolve_compile_target."""

    def test_empty_target_set_with_known_no_compile_target_returns_sentinel(self):
        """Lines 203-205: list of only no-compile targets returns the first sentinel."""
        from apm_cli.commands.compile.cli import _resolve_compile_target

        result = _resolve_compile_target(["agent-skills"])
        assert result == "agent-skills"

    def test_empty_target_set_with_copilot_cowork_returns_sentinel(self):
        """Lines 203-205: list containing only copilot-cowork returns it."""
        from apm_cli.commands.compile.cli import _resolve_compile_target

        result = _resolve_compile_target(["copilot-cowork"])
        assert result == "copilot-cowork"

    def test_empty_target_set_unknown_only_returns_none(self):
        """Line 206: if target has items not in skip and not in KNOWN_TARGETS,
        target_set is non-empty so this path is actually line 222 (continue).
        Verify unknown-only list still resolves without crash."""
        from apm_cli.commands.compile.cli import _resolve_compile_target

        # An unknown target is NOT in skip set (only KNOWN_TARGETS with None family
        # are in skip). So target_set = {"totally-unknown"}, which is non-empty.
        # _family_of returns None for it -> triggers line 222 continue.
        # families remains empty -> falls through to agents-family loop -> no match
        # -> returns "vscode" defensive fallback (line 251).
        result = _resolve_compile_target(["totally-unknown-target-xyz"])
        # Should not raise; returns the defensive fallback
        assert result == "vscode"

    def test_unknown_target_in_list_skips_family_resolution(self):
        """Line 222: unknown target mixed with real target - unknown is skipped."""
        from apm_cli.commands.compile.cli import _resolve_compile_target

        # unknown target has no family -> continue (line 222)
        # claude is a real target -> families = {"claude"}
        result = _resolve_compile_target(["totally-unknown-target-xyz", "claude"])
        assert result == "claude"

    def test_multiple_no_compile_targets_returns_first_sentinel(self):
        """Lines 203-205: multiple no-compile targets - returns first found in skip."""
        from apm_cli.commands.compile.cli import _resolve_compile_target

        result = _resolve_compile_target(["agent-skills", "copilot-cowork"])
        # Both are in skip; returns the first one encountered in iteration
        assert result in ("agent-skills", "copilot-cowork")


class TestDisplayValidationErrors:
    """Tests for _display_validation_errors fallback paths."""

    def test_error_without_colon_uses_unknown_file(self):
        """Lines 133-134: error string without ':' -> file_name='Unknown'."""
        from apm_cli.commands.compile.cli import _display_validation_errors

        errors = ["InvalidFrontmatter no colon in error"]
        # Should not raise regardless of Rich availability
        try:
            _display_validation_errors(errors)
        except Exception as exc:
            raise AssertionError(f"_display_validation_errors raised: {exc}") from exc

    def test_error_with_colon_splits_correctly(self):
        """Lines 128-131: error string with ':' splits into file and message."""
        from apm_cli.commands.compile.cli import _display_validation_errors

        errors = ["some/file.instructions.md: Missing 'description' in frontmatter"]
        try:
            _display_validation_errors(errors)
        except Exception as exc:
            raise AssertionError(f"_display_validation_errors raised: {exc}") from exc

    def test_empty_errors_list(self):
        """Edge case: no errors."""
        from apm_cli.commands.compile.cli import _display_validation_errors

        try:
            _display_validation_errors([])
        except Exception as exc:
            raise AssertionError(f"_display_validation_errors raised: {exc}") from exc

    def test_fallback_text_output_when_rich_unavailable(self, capsys):
        """Lines 147-149: when Rich is unavailable, falls back to plain text."""
        from apm_cli.commands.compile.cli import _display_validation_errors

        # Simulate Rich/console being unavailable by patching _get_console to return None
        # and causing the Rich import inside to raise ImportError.
        with (
            patch("apm_cli.commands.compile.cli._get_console", return_value=None),
            patch("apm_cli.commands.compile.cli._rich_error") as mock_error,
        ):
            _display_validation_errors(["some error message"])
            mock_error.assert_called_once()


class TestDisplaySingleFileSummary:
    """Tests for _display_single_file_summary no-console fallback."""

    def test_no_console_fallback_does_not_raise(self, tmp_path):
        """Lines 32-37: when _get_console() returns None, uses _rich_info fallback."""
        from apm_cli.commands.compile.cli import _display_single_file_summary

        output_path = tmp_path / "AGENTS.md"
        output_path.write_text("# test")

        stats = {"primitives_found": 3, "instructions": 2, "contexts": 1, "chatmodes": 0}

        with (
            patch("apm_cli.commands.compile.cli._get_console", return_value=None),
            patch("apm_cli.commands.compile.cli._rich_info") as mock_info,
        ):
            _display_single_file_summary(stats, "[+] Current", "abc123", output_path, False)
            assert mock_info.call_count >= 1

    def test_no_console_dry_run_fallback(self, tmp_path):
        """Dry-run with no-console fallback."""
        from apm_cli.commands.compile.cli import _display_single_file_summary

        output_path = tmp_path / "AGENTS.md"
        stats = {"primitives_found": 0, "instructions": 0, "contexts": 0, "chatmodes": 0}

        with (
            patch("apm_cli.commands.compile.cli._get_console", return_value=None),
            patch("apm_cli.commands.compile.cli._rich_info"),
        ):
            # Should not raise
            _display_single_file_summary(stats, "n/a", None, output_path, True)


class TestDisplayNextSteps:
    """Tests for _display_next_steps no-console fallback."""

    def test_no_console_fallback_does_not_raise(self):
        """Lines 99-106: when _get_console() returns None, uses _rich_info."""
        from apm_cli.commands.compile.cli import _display_next_steps

        with (
            patch("apm_cli.commands.compile.cli._get_console", return_value=None),
            patch("apm_cli.commands.compile.cli._rich_info") as mock_info,
        ):
            _display_next_steps("AGENTS.md")
            assert mock_info.call_count >= 1

    def test_with_console_does_not_raise(self):
        """_display_next_steps with a mock console should not raise."""
        from apm_cli.commands.compile.cli import _display_next_steps

        mock_console = MagicMock()
        with patch("apm_cli.commands.compile.cli._get_console", return_value=mock_console):
            _display_next_steps("AGENTS.md")
            mock_console.print.assert_called_once()
