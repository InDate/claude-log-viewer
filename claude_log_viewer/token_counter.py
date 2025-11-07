"""
Token counter for Claude Code JSONL entries using tiktoken.

Counts tokens from actual message content to understand what's consuming
the token budget, including tool results, user messages, assistant responses,
thinking blocks, and tool uses.
"""
import json
import tiktoken
from typing import Dict, Any


# Initialize tiktoken encoding once
# cl100k_base is used for Claude models (same as GPT-4)
_encoding = None


def get_encoding():
    """Get or initialize the tiktoken encoding."""
    global _encoding
    if _encoding is None:
        _encoding = tiktoken.get_encoding("cl100k_base")
    return _encoding


def count_tokens(text: str) -> int:
    """Count tokens in a text string."""
    if not text:
        return 0
    encoding = get_encoding()
    return len(encoding.encode(text))


def count_message_tokens(entry: Dict[str, Any]) -> int:
    """
    Count tokens for everything that goes to/from Claude in this entry.

    This includes:
    - User message content
    - Assistant text responses
    - Thinking blocks
    - Tool use parameters (serialized)
    - Tool result content
    - System messages

    Args:
        entry: A single JSONL entry

    Returns:
        Total token count for this entry
    """
    total_tokens = 0

    # Extract message content
    message = entry.get('message', {})
    content = message.get('content', [])

    # Handle simple string content (common for user messages)
    if isinstance(content, str):
        total_tokens += count_tokens(content)
        return total_tokens

    # Handle structured content array
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue

            item_type = item.get('type', '')

            if item_type == 'text':
                # Assistant text output
                text = item.get('text', '')
                total_tokens += count_tokens(text)

            elif item_type == 'thinking':
                # Thinking blocks - these count toward context!
                thinking = item.get('thinking', '')
                total_tokens += count_tokens(thinking)

            elif item_type == 'tool_use':
                # Tool calls - serialize the entire tool_use object
                # This includes tool name, id, and all input parameters
                try:
                    tool_json = json.dumps(item, ensure_ascii=False)
                    total_tokens += count_tokens(tool_json)
                except (TypeError, ValueError):
                    # If serialization fails, estimate from string representation
                    total_tokens += count_tokens(str(item))

            elif item_type == 'tool_result':
                # Tool results - often the biggest token consumer!
                result_content = item.get('content', '')

                # Check if this is an image result - images use vision tokens, not text tokens
                if isinstance(result_content, list):
                    for content_item in result_content:
                        if isinstance(content_item, dict):
                            content_type = content_item.get('type', '')

                            if content_type == 'image':
                                # Images use ~85 tokens per tile (varies by size)
                                # Use a rough approximation: 1 image = ~750 tokens (average)
                                total_tokens += 750
                            elif content_type == 'text':
                                # Regular text content
                                text = content_item.get('text', '')
                                total_tokens += count_tokens(text)
                            else:
                                # Other content types
                                try:
                                    item_json = json.dumps(content_item, ensure_ascii=False)
                                    total_tokens += count_tokens(item_json)
                                except (TypeError, ValueError):
                                    total_tokens += count_tokens(str(content_item))
                elif isinstance(result_content, str):
                    total_tokens += count_tokens(result_content)
                elif isinstance(result_content, dict):
                    # Check if it's an image object
                    if result_content.get('type') == 'image':
                        total_tokens += 750  # Approximate image token cost
                    else:
                        # Serialize structured results
                        try:
                            result_json = json.dumps(result_content, ensure_ascii=False)
                            total_tokens += count_tokens(result_json)
                        except (TypeError, ValueError):
                            total_tokens += count_tokens(str(result_content))
                else:
                    # Other types - convert to string
                    total_tokens += count_tokens(str(result_content))

    # Handle system messages (type='system')
    if entry.get('type') == 'system':
        system_content = entry.get('content', '')
        if isinstance(system_content, str):
            total_tokens += count_tokens(system_content)

    return total_tokens


def format_token_count(token_count: int) -> str:
    """
    Format token count for display.

    Examples:
        156 -> "~156"
        2450 -> "~2.5k"
        15600 -> "~15.6k"
        125000 -> "~125k"

    Args:
        token_count: Number of tokens

    Returns:
        Formatted string like "~2.5k" or "~156"
    """
    if token_count == 0:
        return "0"

    if token_count < 1000:
        return f"~{token_count}"

    # Format as k with appropriate precision
    k_value = token_count / 1000
    if k_value >= 100:
        # 100k+ - no decimal
        return f"~{int(k_value)}k"
    elif k_value >= 10:
        # 10k-99k - 1 decimal
        return f"~{k_value:.1f}k"
    else:
        # 1k-9.9k - 1 decimal
        return f"~{k_value:.1f}k"


if __name__ == '__main__':
    # Test the token counter
    test_entry = {
        'message': {
            'content': [
                {
                    'type': 'text',
                    'text': 'This is a test message.'
                },
                {
                    'type': 'tool_use',
                    'name': 'Read',
                    'input': {'file_path': '/path/to/file.py'}
                },
                {
                    'type': 'tool_result',
                    'content': 'This is a very long file content that would consume many tokens...' * 100
                }
            ]
        }
    }

    tokens = count_message_tokens(test_entry)
    formatted = format_token_count(tokens)
    print(f"Test entry tokens: {tokens} ({formatted})")
