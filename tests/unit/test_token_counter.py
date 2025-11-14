"""
Tests for token counting functionality using tiktoken.

These tests verify:
- Basic token counting with tiktoken
- Message token counting across different content types
- Token count formatting for display
- Image token approximation
- Tool use/result serialization
"""

import pytest
from unittest.mock import Mock, patch


@pytest.mark.unit
class TestBasicTokenCounting:
    """Tests for basic token counting functions."""

    def test_count_tokens_simple_text(self):
        """Verify basic text token counting works."""
        from claude_log_viewer.token_counter import count_tokens

        # Simple English text
        text = "Hello, world!"
        tokens = count_tokens(text)

        assert tokens > 0
        assert isinstance(tokens, int)

    def test_count_tokens_empty_string(self):
        """Verify empty string returns 0 tokens."""
        from claude_log_viewer.token_counter import count_tokens

        assert count_tokens("") == 0
        assert count_tokens(None) == 0

    def test_count_tokens_whitespace(self):
        """Verify whitespace is counted."""
        from claude_log_viewer.token_counter import count_tokens

        # Whitespace should have some tokens
        tokens = count_tokens("    \n\n\t")
        assert tokens > 0

    def test_count_tokens_long_text(self):
        """Verify token count scales with text length."""
        from claude_log_viewer.token_counter import count_tokens

        short_text = "Hello"
        long_text = "Hello" * 100

        short_tokens = count_tokens(short_text)
        long_tokens = count_tokens(long_text)

        # Long text should have proportionally more tokens
        assert long_tokens > short_tokens * 50

    def test_count_tokens_unicode(self):
        """Verify Unicode text is counted correctly."""
        from claude_log_viewer.token_counter import count_tokens

        unicode_text = "Hello 世界 🌍"
        tokens = count_tokens(unicode_text)

        assert tokens > 0

    def test_get_encoding_singleton(self):
        """Verify encoding is initialized once and reused."""
        from claude_log_viewer.token_counter import get_encoding

        # Get encoding twice
        enc1 = get_encoding()
        enc2 = get_encoding()

        # Should be the same object (singleton pattern)
        assert enc1 is enc2

    def test_get_encoding_cl100k_base(self):
        """Verify we're using cl100k_base encoding."""
        from claude_log_viewer.token_counter import get_encoding

        encoding = get_encoding()

        # Verify it's cl100k_base by checking encoding name
        assert encoding.name == "cl100k_base"


@pytest.mark.unit
class TestMessageTokenCounting:
    """Tests for count_message_tokens function."""

    def test_count_simple_string_content(self):
        """Verify simple string content is counted."""
        from claude_log_viewer.token_counter import count_message_tokens

        entry = {
            'message': {
                'content': 'This is a simple string message.'
            }
        }

        tokens = count_message_tokens(entry)
        assert tokens > 0

    def test_count_text_block(self):
        """Verify text blocks are counted."""
        from claude_log_viewer.token_counter import count_message_tokens

        entry = {
            'message': {
                'content': [
                    {
                        'type': 'text',
                        'text': 'This is a text block with multiple words.'
                    }
                ]
            }
        }

        tokens = count_message_tokens(entry)
        assert tokens > 0

    def test_count_thinking_block(self):
        """Verify thinking blocks are counted."""
        from claude_log_viewer.token_counter import count_message_tokens

        entry = {
            'message': {
                'content': [
                    {
                        'type': 'thinking',
                        'thinking': 'This is internal thinking that counts toward tokens.'
                    }
                ]
            }
        }

        tokens = count_message_tokens(entry)
        assert tokens > 0

    def test_count_tool_use(self):
        """Verify tool use blocks are serialized and counted."""
        from claude_log_viewer.token_counter import count_message_tokens

        entry = {
            'message': {
                'content': [
                    {
                        'type': 'tool_use',
                        'id': 'tool_123',
                        'name': 'Read',
                        'input': {
                            'file_path': '/path/to/very/long/file/path.py',
                            'offset': 100,
                            'limit': 500
                        }
                    }
                ]
            }
        }

        tokens = count_message_tokens(entry)
        # Should count the entire JSON serialization
        assert tokens > 10  # At least some tokens for the structure

    def test_count_tool_result_text(self):
        """Verify tool result text content is counted."""
        from claude_log_viewer.token_counter import count_message_tokens

        large_content = "This is file content.\n" * 100

        entry = {
            'message': {
                'content': [
                    {
                        'type': 'tool_result',
                        'tool_use_id': 'tool_123',
                        'content': large_content
                    }
                ]
            }
        }

        tokens = count_message_tokens(entry)
        # Large content should have many tokens
        assert tokens > 100

    def test_count_tool_result_image(self):
        """Verify tool result images use ~750 token approximation."""
        from claude_log_viewer.token_counter import count_message_tokens

        entry = {
            'message': {
                'content': [
                    {
                        'type': 'tool_result',
                        'tool_use_id': 'tool_123',
                        'content': [
                            {
                                'type': 'image',
                                'source': {
                                    'type': 'base64',
                                    'media_type': 'image/png',
                                    'data': 'iVBORw0KG...'
                                }
                            }
                        ]
                    }
                ]
            }
        }

        tokens = count_message_tokens(entry)
        # Should use ~750 token approximation for images
        assert tokens == 750

    def test_count_tool_result_multiple_images(self):
        """Verify multiple images each count as ~750 tokens."""
        from claude_log_viewer.token_counter import count_message_tokens

        entry = {
            'message': {
                'content': [
                    {
                        'type': 'tool_result',
                        'tool_use_id': 'tool_123',
                        'content': [
                            {'type': 'image', 'source': {}},
                            {'type': 'image', 'source': {}},
                            {'type': 'image', 'source': {}}
                        ]
                    }
                ]
            }
        }

        tokens = count_message_tokens(entry)
        # 3 images * 750 tokens each
        assert tokens == 750 * 3

    def test_count_tool_result_mixed_content(self):
        """Verify mixed text and image content is counted."""
        from claude_log_viewer.token_counter import count_message_tokens

        entry = {
            'message': {
                'content': [
                    {
                        'type': 'tool_result',
                        'tool_use_id': 'tool_123',
                        'content': [
                            {
                                'type': 'text',
                                'text': 'Here is a screenshot showing the issue:'
                            },
                            {
                                'type': 'image',
                                'source': {}
                            }
                        ]
                    }
                ]
            }
        }

        tokens = count_message_tokens(entry)
        # Should count both text and image tokens
        assert tokens > 750  # At least image + some text

    def test_count_system_message(self):
        """Verify system messages are counted."""
        from claude_log_viewer.token_counter import count_message_tokens

        entry = {
            'type': 'system',
            'content': 'This is a system message with important information.'
        }

        tokens = count_message_tokens(entry)
        assert tokens > 0

    def test_count_multiple_content_blocks(self):
        """Verify multiple content blocks are all counted."""
        from claude_log_viewer.token_counter import count_message_tokens

        entry = {
            'message': {
                'content': [
                    {'type': 'text', 'text': 'First block'},
                    {'type': 'text', 'text': 'Second block'},
                    {'type': 'text', 'text': 'Third block'}
                ]
            }
        }

        tokens = count_message_tokens(entry)
        # Should count all three blocks
        assert tokens > 5

    def test_count_empty_entry(self):
        """Verify empty entries return 0 tokens."""
        from claude_log_viewer.token_counter import count_message_tokens

        assert count_message_tokens({}) == 0
        assert count_message_tokens({'message': {}}) == 0
        assert count_message_tokens({'message': {'content': []}}) == 0

    def test_count_non_dict_content_items(self):
        """Verify non-dict content items are skipped."""
        from claude_log_viewer.token_counter import count_message_tokens

        entry = {
            'message': {
                'content': [
                    'invalid',  # Not a dict
                    {'type': 'text', 'text': 'Valid block'},
                    123,  # Not a dict
                ]
            }
        }

        # Should only count the valid text block
        tokens = count_message_tokens(entry)
        assert tokens > 0

    def test_count_tool_use_serialization_error(self):
        """Verify tool use with circular refs falls back to str()."""
        from claude_log_viewer.token_counter import count_message_tokens

        # Create circular reference
        circular = {'type': 'tool_use', 'name': 'Test'}
        circular['self'] = circular

        entry = {
            'message': {
                'content': [circular]
            }
        }

        # Should handle serialization error gracefully
        tokens = count_message_tokens(entry)
        assert tokens >= 0  # Should not crash


@pytest.mark.unit
class TestTokenFormatting:
    """Tests for format_token_count function."""

    def test_format_zero(self):
        """Verify 0 is formatted as '0'."""
        from claude_log_viewer.token_counter import format_token_count

        assert format_token_count(0) == "0"

    def test_format_under_1k(self):
        """Verify counts under 1000 use ~N format."""
        from claude_log_viewer.token_counter import format_token_count

        assert format_token_count(1) == "~1"
        assert format_token_count(156) == "~156"
        assert format_token_count(999) == "~999"

    def test_format_1k_to_10k(self):
        """Verify 1k-9.9k uses ~N.Nk format with 1 decimal."""
        from claude_log_viewer.token_counter import format_token_count

        assert format_token_count(1000) == "~1.0k"
        assert format_token_count(2500) == "~2.5k"
        assert format_token_count(9999) == "~10.0k"

    def test_format_10k_to_100k(self):
        """Verify 10k-99k uses ~NN.Nk format with 1 decimal."""
        from claude_log_viewer.token_counter import format_token_count

        assert format_token_count(15000) == "~15.0k"
        assert format_token_count(15600) == "~15.6k"
        assert format_token_count(99999) == "~100.0k"

    def test_format_100k_plus(self):
        """Verify 100k+ uses ~NNNk format with no decimal."""
        from claude_log_viewer.token_counter import format_token_count

        assert format_token_count(100000) == "~100k"
        assert format_token_count(125000) == "~125k"
        assert format_token_count(999999) == "~999k"
        assert format_token_count(1500000) == "~1500k"


@pytest.mark.integration
class TestTokenCountingIntegration:
    """Integration tests using sample JSONL entries."""

    def test_count_user_message(self, sample_jsonl_entries):
        """Test counting user message from fixture."""
        from claude_log_viewer.token_counter import count_message_tokens

        # First entry in fixture is a user message
        user_entry = sample_jsonl_entries[0]
        tokens = count_message_tokens(user_entry)

        # User message "Hello, can you help me with Python?"
        assert tokens > 0
        assert tokens < 50  # Reasonable range for short message

    def test_count_assistant_response(self, sample_jsonl_entries):
        """Test counting assistant response from fixture."""
        from claude_log_viewer.token_counter import count_message_tokens

        # Second entry is assistant response
        assistant_entry = sample_jsonl_entries[1]
        tokens = count_message_tokens(assistant_entry)

        # Longer assistant response
        assert tokens > 10
        assert tokens < 100

    def test_count_tool_use_entry(self, sample_jsonl_entries):
        """Test counting tool use from fixture."""
        from claude_log_viewer.token_counter import count_message_tokens

        # Third entry is tool use
        tool_use_entry = sample_jsonl_entries[2]
        tokens = count_message_tokens(tool_use_entry)

        # Tool use should have tokens for JSON structure
        assert tokens > 5

    def test_count_tool_result_entry(self, sample_jsonl_entries):
        """Test counting tool result from fixture."""
        from claude_log_viewer.token_counter import count_message_tokens

        # Fourth entry is tool result
        tool_result_entry = sample_jsonl_entries[3]
        tokens = count_message_tokens(tool_result_entry)

        # Tool result with code content
        assert tokens > 10

    def test_count_system_entry(self, sample_jsonl_entries):
        """Test counting system message from fixture."""
        from claude_log_viewer.token_counter import count_message_tokens

        # Fifth entry is system message
        system_entry = sample_jsonl_entries[4]
        tokens = count_message_tokens(system_entry)

        # System message "Session started"
        assert tokens > 0
        assert tokens < 20

    def test_total_session_tokens(self, sample_jsonl_entries):
        """Test counting total tokens across all entries."""
        from claude_log_viewer.token_counter import count_message_tokens

        total = sum(count_message_tokens(entry) for entry in sample_jsonl_entries)

        # Total should be sum of all individual entries
        assert total > 0
        assert total < 500  # Reasonable upper bound
