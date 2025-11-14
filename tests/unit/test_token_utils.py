"""
Tests for token_utils.py - Usage field priority and token extraction.

These tests verify:
- extract_tokens_from_entry prioritizes usage field over tiktoken
- Proper handling of all 4 token types (input, output, cache_creation, cache_read)
- Fallback to tiktoken when usage field missing
- Handling of None/null values
- Token breakdown extraction
"""

import pytest
from unittest.mock import Mock, patch


@pytest.mark.unit
class TestExtractTokensFromEntry:
    """Tests for extract_tokens_from_entry function."""

    def test_usage_field_complete(self):
        """Verify complete usage field is used (preferred method)."""
        from claude_log_viewer.token_utils import extract_tokens_from_entry

        entry = {
            'message': {
                'usage': {
                    'input_tokens': 100,
                    'output_tokens': 50,
                    'cache_creation_input_tokens': 200,
                    'cache_read_input_tokens': 5000
                }
            }
        }

        tokens = extract_tokens_from_entry(entry)

        # Should sum all 4 token types: 100 + 50 + 200 + 5000 = 5350
        assert tokens == 5350

    def test_usage_field_partial_no_cache(self):
        """Verify partial usage field works (missing cache tokens)."""
        from claude_log_viewer.token_utils import extract_tokens_from_entry

        entry = {
            'message': {
                'usage': {
                    'input_tokens': 100,
                    'output_tokens': 50
                }
            }
        }

        tokens = extract_tokens_from_entry(entry)

        # Should sum available fields: 100 + 50 = 150
        assert tokens == 150

    def test_usage_field_only_cache_creation(self):
        """Verify cache_creation_input_tokens is included."""
        from claude_log_viewer.token_utils import extract_tokens_from_entry

        entry = {
            'message': {
                'usage': {
                    'input_tokens': 100,
                    'output_tokens': 50,
                    'cache_creation_input_tokens': 1000
                }
            }
        }

        tokens = extract_tokens_from_entry(entry)

        # Should include cache creation: 100 + 50 + 1000 = 1150
        assert tokens == 1150

    def test_usage_field_only_cache_read(self):
        """Verify cache_read_input_tokens is included."""
        from claude_log_viewer.token_utils import extract_tokens_from_entry

        entry = {
            'message': {
                'usage': {
                    'input_tokens': 100,
                    'output_tokens': 50,
                    'cache_read_input_tokens': 3000
                }
            }
        }

        tokens = extract_tokens_from_entry(entry)

        # Should include cache read: 100 + 50 + 3000 = 3150
        assert tokens == 3150

    def test_usage_field_none_values(self):
        """Verify None values are treated as 0."""
        from claude_log_viewer.token_utils import extract_tokens_from_entry

        entry = {
            'message': {
                'usage': {
                    'input_tokens': None,
                    'output_tokens': 50,
                    'cache_creation_input_tokens': 0,
                    'cache_read_input_tokens': None
                }
            }
        }

        tokens = extract_tokens_from_entry(entry)

        # None should be treated as 0: 0 + 50 + 0 + 0 = 50
        assert tokens == 50

    def test_usage_field_zero_values(self):
        """Verify explicit 0 values work correctly."""
        from claude_log_viewer.token_utils import extract_tokens_from_entry

        entry = {
            'message': {
                'usage': {
                    'input_tokens': 100,
                    'output_tokens': 0,
                    'cache_creation_input_tokens': 0,
                    'cache_read_input_tokens': 0
                }
            }
        }

        tokens = extract_tokens_from_entry(entry)

        # Zeros should be treated as 0: 100 + 0 + 0 + 0 = 100
        assert tokens == 100

    def test_fallback_to_tiktoken(self):
        """Verify fallback to tiktoken when usage field missing."""
        from claude_log_viewer.token_utils import extract_tokens_from_entry

        entry = {
            'message': {
                'content': [
                    {
                        'type': 'text',
                        'text': 'Hello, this is a test message for tiktoken estimation.'
                    }
                ]
            }
        }

        tokens = extract_tokens_from_entry(entry)

        # Should fall back to tiktoken estimation
        assert tokens > 0

    def test_empty_entry_returns_zero(self):
        """Verify empty entries return 0."""
        from claude_log_viewer.token_utils import extract_tokens_from_entry

        assert extract_tokens_from_entry({}) == 0
        assert extract_tokens_from_entry({'message': {}}) == 0

    def test_usage_field_takes_priority_over_content(self):
        """Verify usage field is used even when content exists."""
        from claude_log_viewer.token_utils import extract_tokens_from_entry

        entry = {
            'message': {
                'usage': {
                    'input_tokens': 100,
                    'output_tokens': 50
                },
                'content': [
                    {
                        'type': 'text',
                        'text': 'This content should be ignored when usage field exists.'
                    }
                ]
            }
        }

        tokens = extract_tokens_from_entry(entry)

        # Should use usage field (150), not tiktoken from content
        assert tokens == 150

    def test_tiktoken_error_handling(self):
        """Verify tiktoken errors are caught and return 0."""
        from claude_log_viewer.token_utils import extract_tokens_from_entry

        # Entry with invalid structure that might cause tiktoken error
        entry = {
            'message': {
                'content': None  # Invalid structure
            }
        }

        # Should handle error gracefully
        tokens = extract_tokens_from_entry(entry)
        assert tokens >= 0  # Should not crash

    def test_verbose_mode_logs_errors(self, capsys):
        """Verify verbose mode logs tiktoken errors to stderr."""
        from claude_log_viewer.token_utils import extract_tokens_from_entry

        # Mock tiktoken to raise error
        with patch('claude_log_viewer.token_utils.count_message_tokens_tiktoken', side_effect=Exception("Test error")):
            entry = {
                'message': {
                    'content': 'test'
                }
            }

            tokens = extract_tokens_from_entry(entry, verbose=True)

            # Should log warning to stderr
            captured = capsys.readouterr()
            assert 'Warning: Failed to count tokens' in captured.err


@pytest.mark.unit
class TestExtractTokenBreakdown:
    """Tests for extract_token_breakdown function."""

    def test_breakdown_with_usage_field(self):
        """Verify breakdown from usage field includes all token types."""
        from claude_log_viewer.token_utils import extract_token_breakdown

        entry = {
            'message': {
                'usage': {
                    'input_tokens': 100,
                    'output_tokens': 50,
                    'cache_creation_input_tokens': 200,
                    'cache_read_input_tokens': 5000
                }
            }
        }

        breakdown = extract_token_breakdown(entry)

        assert breakdown['input_tokens'] == 100
        assert breakdown['output_tokens'] == 50
        assert breakdown['cache_creation_tokens'] == 200
        assert breakdown['cache_read_tokens'] == 5000
        assert breakdown['total_tokens'] == 5350
        assert breakdown['source'] == 'usage_field'

    def test_breakdown_with_tiktoken_fallback(self):
        """Verify breakdown falls back to tiktoken estimation."""
        from claude_log_viewer.token_utils import extract_token_breakdown

        entry = {
            'message': {
                'content': [
                    {
                        'type': 'text',
                        'text': 'Test message for tiktoken estimation.'
                    }
                ]
            }
        }

        breakdown = extract_token_breakdown(entry)

        # Should use tiktoken estimation
        assert breakdown['total_tokens'] > 0
        assert breakdown['input_tokens'] > 0  # Estimate goes to input_tokens
        assert breakdown['output_tokens'] == 0  # Can't break down estimate
        assert breakdown['cache_creation_tokens'] == 0
        assert breakdown['cache_read_tokens'] == 0
        assert breakdown['source'] == 'tiktoken_estimate'

    def test_breakdown_empty_entry(self):
        """Verify empty entry returns zeros."""
        from claude_log_viewer.token_utils import extract_token_breakdown

        breakdown = extract_token_breakdown({})

        assert breakdown['input_tokens'] == 0
        assert breakdown['output_tokens'] == 0
        assert breakdown['cache_creation_tokens'] == 0
        assert breakdown['cache_read_tokens'] == 0
        assert breakdown['total_tokens'] == 0
        assert breakdown['source'] == 'tiktoken_estimate'

    def test_breakdown_partial_usage(self):
        """Verify breakdown with partial usage field."""
        from claude_log_viewer.token_utils import extract_token_breakdown

        entry = {
            'message': {
                'usage': {
                    'input_tokens': 100,
                    'output_tokens': 50
                }
            }
        }

        breakdown = extract_token_breakdown(entry)

        assert breakdown['input_tokens'] == 100
        assert breakdown['output_tokens'] == 50
        assert breakdown['cache_creation_tokens'] == 0
        assert breakdown['cache_read_tokens'] == 0
        assert breakdown['total_tokens'] == 150
        assert breakdown['source'] == 'usage_field'

    def test_breakdown_none_values(self):
        """Verify None values are treated as 0 in breakdown."""
        from claude_log_viewer.token_utils import extract_token_breakdown

        entry = {
            'message': {
                'usage': {
                    'input_tokens': None,
                    'output_tokens': 50,
                    'cache_creation_input_tokens': None,
                    'cache_read_input_tokens': 3000
                }
            }
        }

        breakdown = extract_token_breakdown(entry)

        assert breakdown['input_tokens'] == 0
        assert breakdown['output_tokens'] == 50
        assert breakdown['cache_creation_tokens'] == 0
        assert breakdown['cache_read_tokens'] == 3000
        assert breakdown['total_tokens'] == 3050

    def test_breakdown_tiktoken_error(self):
        """Verify tiktoken errors return zeros."""
        from claude_log_viewer.token_utils import extract_token_breakdown

        # Mock tiktoken to raise error
        with patch('claude_log_viewer.token_utils.count_message_tokens_tiktoken', side_effect=Exception("Test error")):
            entry = {
                'message': {
                    'content': 'test'
                }
            }

            breakdown = extract_token_breakdown(entry)

            # Should return zeros on error
            assert breakdown['total_tokens'] == 0
            assert breakdown['source'] == 'tiktoken_estimate'


@pytest.mark.unit
class TestCountMessageTokensTiktoken:
    """Tests for count_message_tokens_tiktoken fallback function."""

    def test_tiktoken_fallback_works(self):
        """Verify tiktoken fallback calls token_counter."""
        from claude_log_viewer.token_utils import count_message_tokens_tiktoken

        entry = {
            'message': {
                'content': [
                    {
                        'type': 'text',
                        'text': 'Test message for tiktoken.'
                    }
                ]
            }
        }

        tokens = count_message_tokens_tiktoken(entry)

        # Should return token count from token_counter module
        assert tokens > 0

    def test_tiktoken_import_error(self):
        """Verify ImportError is raised if token_counter unavailable."""
        from claude_log_viewer.token_utils import count_message_tokens_tiktoken

        # Mock import to fail
        with patch('claude_log_viewer.token_utils.count_message_tokens', side_effect=ImportError("Module not found")):
            with pytest.raises(ImportError, match="Failed to import token_counter"):
                count_message_tokens_tiktoken({})


@pytest.mark.integration
class TestTokenUtilsIntegration:
    """Integration tests with sample JSONL data."""

    def test_extract_tokens_usage_field(self, sample_jsonl_entries):
        """Test extraction with usage field present."""
        from claude_log_viewer.token_utils import extract_tokens_from_entry

        # Create entry with usage field
        entry_with_usage = {
            'message': {
                'usage': {
                    'input_tokens': 150,
                    'output_tokens': 75,
                    'cache_creation_input_tokens': 0,
                    'cache_read_input_tokens': 0
                }
            }
        }

        tokens = extract_tokens_from_entry(entry_with_usage)
        assert tokens == 225

    def test_extract_tokens_content_fallback(self, sample_jsonl_entries):
        """Test extraction falls back to content analysis."""
        from claude_log_viewer.token_utils import extract_tokens_from_entry

        # Use first sample entry (user message)
        user_entry = sample_jsonl_entries[0]

        tokens = extract_tokens_from_entry(user_entry)

        # Should use tiktoken fallback (no usage field in fixture)
        assert tokens > 0

    def test_breakdown_across_entry_types(self, sample_jsonl_entries):
        """Test breakdown works for all sample entry types."""
        from claude_log_viewer.token_utils import extract_token_breakdown

        for entry in sample_jsonl_entries:
            breakdown = extract_token_breakdown(entry)

            # Every entry should have a valid breakdown
            assert 'total_tokens' in breakdown
            assert 'source' in breakdown
            assert breakdown['total_tokens'] >= 0

    def test_cache_tokens_summed_correctly(self):
        """Verify cache tokens are properly included in totals."""
        from claude_log_viewer.token_utils import extract_tokens_from_entry

        # Entry with significant cache usage
        entry = {
            'message': {
                'usage': {
                    'input_tokens': 50,
                    'output_tokens': 25,
                    'cache_creation_input_tokens': 10000,  # Large cache creation
                    'cache_read_input_tokens': 50000  # Large cache read
                }
            }
        }

        tokens = extract_tokens_from_entry(entry)

        # Cache tokens should be included: 50 + 25 + 10000 + 50000 = 60075
        assert tokens == 60075

    def test_usage_field_priority_demonstrated(self):
        """Demonstrate that usage field takes priority over content."""
        from claude_log_viewer.token_utils import extract_tokens_from_entry

        # Entry with both usage field and content
        entry_with_both = {
            'message': {
                'usage': {
                    'input_tokens': 500,
                    'output_tokens': 250
                },
                'content': [
                    {
                        'type': 'text',
                        'text': 'Short text'  # Would be ~3 tokens if counted
                    }
                ]
            }
        }

        tokens = extract_tokens_from_entry(entry_with_both)

        # Should use usage field (750), not tiktoken (~3)
        assert tokens == 750

        # Now test without usage field
        entry_content_only = {
            'message': {
                'content': [
                    {
                        'type': 'text',
                        'text': 'Short text'
                    }
                ]
            }
        }

        tokens_fallback = extract_tokens_from_entry(entry_content_only)

        # Should use tiktoken (much smaller)
        assert tokens_fallback < 100
        assert tokens_fallback != 750
