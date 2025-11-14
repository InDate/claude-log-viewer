"""
Shared token counting utilities for Claude Log Viewer.

This module provides token extraction and counting following the ccusage methodology:
- Primary: Extract from JSONL message.usage field (official Claude API values)
- Fallback: tiktoken estimation when usage field is missing
- Cache tokens: Always included (cache_creation + cache_read)

Used by: snapshot_pipeline.py, analyze_increment.py, and other analysis tools.
"""
from typing import Dict, Any, Optional


def extract_tokens_from_entry(entry: Dict[str, Any], verbose: bool = False) -> int:
    """
    Extract token count from a JSONL entry using ccusage methodology.

    Token counting priority:
    1. JSONL message.usage field (preferred - official Claude API values)
       - Includes all 4 fields: input, output, cache_creation, cache_read
    2. Tiktoken estimation (fallback when usage field missing)

    Args:
        entry: JSONL log entry dictionary
        verbose: Print warnings/debug info to stderr

    Returns:
        Total token count (int)

    Examples:
        >>> entry = {
        ...     "message": {
        ...         "usage": {
        ...             "input_tokens": 100,
        ...             "output_tokens": 50,
        ...             "cache_creation_input_tokens": 200,
        ...             "cache_read_input_tokens": 5000
        ...         }
        ...     }
        ... }
        >>> extract_tokens_from_entry(entry)
        5350

        >>> # Fallback to tiktoken when usage field missing
        >>> entry = {"message": {"content": [{"type": "text", "text": "Hello"}]}}
        >>> extract_tokens_from_entry(entry) > 0
        True
    """
    # Try JSONL usage field first (preferred - official API values)
    tokens = 0
    message = entry.get('message', {})

    if isinstance(message, dict):
        usage = message.get('usage', {})
        if isinstance(usage, dict):
            # Include ALL 4 token fields
            input_tokens = usage.get('input_tokens', 0) or 0
            output_tokens = usage.get('output_tokens', 0) or 0
            cache_creation = usage.get('cache_creation_input_tokens', 0) or 0
            cache_read = usage.get('cache_read_input_tokens', 0) or 0
            tokens = input_tokens + output_tokens + cache_creation + cache_read

    # Fallback to tiktoken if usage field not available
    if tokens == 0:
        try:
            tokens = count_message_tokens_tiktoken(entry)
        except Exception as e:
            if verbose:
                import sys
                print(f"Warning: Failed to count tokens for entry: {e}", file=sys.stderr)
            tokens = 0

    return tokens


def extract_token_breakdown(entry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get detailed breakdown of token types from a JSONL entry.

    Args:
        entry: JSONL log entry dictionary

    Returns:
        Dictionary with:
        - input_tokens: Input tokens (excluding cache)
        - output_tokens: Output/response tokens
        - cache_creation_tokens: Tokens used to create cache
        - cache_read_tokens: Tokens read from cache
        - total_tokens: Sum of all token types
        - source: 'usage_field' or 'tiktoken_estimate'

    Example:
        >>> entry = {
        ...     "message": {
        ...         "usage": {
        ...             "input_tokens": 100,
        ...             "output_tokens": 50,
        ...             "cache_creation_input_tokens": 200,
        ...             "cache_read_input_tokens": 5000
        ...         }
        ...     }
        ... }
        >>> breakdown = extract_token_breakdown(entry)
        >>> breakdown['total_tokens']
        5350
        >>> breakdown['source']
        'usage_field'
    """
    result = {
        'input_tokens': 0,
        'output_tokens': 0,
        'cache_creation_tokens': 0,
        'cache_read_tokens': 0,
        'total_tokens': 0,
        'source': 'tiktoken_estimate'
    }

    # Try JSONL usage field first
    message = entry.get('message', {})
    if isinstance(message, dict):
        usage = message.get('usage', {})
        if isinstance(usage, dict):
            # Extract all 4 token fields
            result['input_tokens'] = usage.get('input_tokens', 0) or 0
            result['output_tokens'] = usage.get('output_tokens', 0) or 0
            result['cache_creation_tokens'] = usage.get('cache_creation_input_tokens', 0) or 0
            result['cache_read_tokens'] = usage.get('cache_read_input_tokens', 0) or 0
            result['total_tokens'] = (
                result['input_tokens'] +
                result['output_tokens'] +
                result['cache_creation_tokens'] +
                result['cache_read_tokens']
            )
            result['source'] = 'usage_field'
            return result

    # Fallback to tiktoken estimation
    try:
        estimated = count_message_tokens_tiktoken(entry)
        result['total_tokens'] = estimated
        # For estimates, we can't break down by type, so put it all in input_tokens
        result['input_tokens'] = estimated
        result['source'] = 'tiktoken_estimate'
    except Exception:
        # If tiktoken fails, return zeros with estimate source
        pass

    return result


def count_message_tokens_tiktoken(entry: Dict[str, Any]) -> int:
    """
    Fallback token estimation using tiktoken.

    Uses cl100k_base encoding (GPT-4 tokenizer) as an approximation
    for Claude tokens. This is NOT exact, but provides a reasonable
    estimate when the official usage field is not available.

    Args:
        entry: JSONL log entry dictionary

    Returns:
        Estimated token count

    Raises:
        ImportError: If tiktoken is not available
        Exception: If token counting fails

    Note:
        This is a lazy import to avoid unnecessary dependencies when
        the usage field is available (which is the common case).
    """
    # Lazy import - only load when needed
    try:
        from claude_log_viewer.token_counter import count_message_tokens
    except ImportError as e:
        raise ImportError(
            "Failed to import token_counter module for tiktoken fallback. "
            "This module is required when JSONL usage field is not available."
        ) from e

    return count_message_tokens(entry)


if __name__ == '__main__':
    # Test the token extraction
    import json

    print("Testing token_utils.py")
    print("=" * 80)
    print()

    # Test 1: Complete usage field
    print("Test 1: Complete usage field (preferred)")
    entry1 = {
        "message": {
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_creation_input_tokens": 200,
                "cache_read_input_tokens": 5000
            }
        }
    }
    tokens1 = extract_tokens_from_entry(entry1)
    breakdown1 = extract_token_breakdown(entry1)
    print(f"  Total tokens: {tokens1}")
    print(f"  Breakdown: {json.dumps(breakdown1, indent=4)}")
    print(f"  Expected: 5350")
    print(f"  Match: {'✓' if tokens1 == 5350 else '✗'}")
    print()

    # Test 2: Partial usage field (missing cache tokens)
    print("Test 2: Partial usage field (missing cache tokens)")
    entry2 = {
        "message": {
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50
            }
        }
    }
    tokens2 = extract_tokens_from_entry(entry2)
    breakdown2 = extract_token_breakdown(entry2)
    print(f"  Total tokens: {tokens2}")
    print(f"  Breakdown: {json.dumps(breakdown2, indent=4)}")
    print(f"  Expected: 150")
    print(f"  Match: {'✓' if tokens2 == 150 else '✗'}")
    print()

    # Test 3: Tiktoken fallback
    print("Test 3: Tiktoken fallback (no usage field)")
    entry3 = {
        "message": {
            "content": [
                {"type": "text", "text": "This is a test message for tiktoken estimation."}
            ]
        }
    }
    tokens3 = extract_tokens_from_entry(entry3, verbose=True)
    breakdown3 = extract_token_breakdown(entry3)
    print(f"  Total tokens: {tokens3}")
    print(f"  Breakdown source: {breakdown3['source']}")
    print(f"  Expected: > 0 (tiktoken estimate)")
    print(f"  Match: {'✓' if tokens3 > 0 else '✗'}")
    print()

    # Test 4: None/null values
    print("Test 4: Handling None/null values")
    entry4 = {
        "message": {
            "usage": {
                "input_tokens": None,
                "output_tokens": 50,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": None
            }
        }
    }
    tokens4 = extract_tokens_from_entry(entry4)
    print(f"  Total tokens: {tokens4}")
    print(f"  Expected: 50 (None treated as 0)")
    print(f"  Match: {'✓' if tokens4 == 50 else '✗'}")
    print()

    print("=" * 80)
    print("All tests complete!")
