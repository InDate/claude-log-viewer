"""
Unit tests for ApiPoller OAuth token refresh functionality.
"""
import json
from unittest.mock import Mock, patch, MagicMock
import pytest
from claude_log_viewer.api_poller import ApiPoller


class TestApiPollerTokenRefresh:
    """Test OAuth token refresh logic in ApiPoller."""

    @patch('claude_log_viewer.api_poller.subprocess.run')
    @patch('claude_log_viewer.api_poller.requests.get')
    def test_token_refresh_on_401_with_new_token(self, mock_get, mock_subprocess):
        """Test that token is refreshed and retry succeeds when a new token is available."""
        # Mock initial token retrieval
        initial_token = "sk-ant-oat01-initial-token"
        refreshed_token = "sk-ant-oat01-refreshed-token"

        keychain_responses = [
            # Initial token (during __init__)
            Mock(returncode=0, stdout=json.dumps({
                'claudeAiOauth': {'accessToken': initial_token}
            })),
            # Refreshed token (during _fetch_usage 401 handling)
            Mock(returncode=0, stdout=json.dumps({
                'claudeAiOauth': {'accessToken': refreshed_token}
            }))
        ]
        mock_subprocess.side_effect = keychain_responses

        # Mock API responses: first 401, then 200 with refreshed token
        mock_response_401 = Mock()
        mock_response_401.status_code = 401

        mock_response_200 = Mock()
        mock_response_200.status_code = 200
        mock_response_200.json.return_value = {
            'data': {
                'five_hour': {
                    'tokens_consumed': 1000,
                    'messages_count': 10,
                    'tokens_limit': 10000,
                    'messages_limit': 100,
                    'utilization': 10.0,
                    'reset_time': '2025-11-13T10:00:00Z'
                },
                'seven_day': {
                    'tokens_consumed': 5000,
                    'messages_count': 50,
                    'tokens_limit': 50000,
                    'messages_limit': 500,
                    'utilization': 10.0,
                    'reset_time': '2025-11-20T00:00:00Z'
                }
            }
        }

        mock_get.side_effect = [mock_response_401, mock_response_200]

        # Create poller
        poller = ApiPoller(poll_interval=10)

        # Verify initial token
        assert poller.oauth_token == initial_token

        # Call _fetch_usage which should trigger refresh
        result = poller._fetch_usage()

        # Verify token was refreshed
        assert poller.oauth_token == refreshed_token

        # Verify result is successful
        assert result is not None
        assert result['five_hour']['tokens_consumed'] == 1000

        # Verify requests.get was called twice (initial + retry)
        assert mock_get.call_count == 2

    @patch('claude_log_viewer.api_poller.subprocess.run')
    @patch('claude_log_viewer.api_poller.requests.get')
    def test_token_refresh_fails_when_token_unchanged(self, mock_get, mock_subprocess):
        """Test that appropriate error is logged when token hasn't been refreshed."""
        # Mock token retrieval - same token both times
        same_token = "sk-ant-oat01-same-token"

        mock_subprocess.return_value = Mock(
            returncode=0,
            stdout=json.dumps({
                'claudeAiOauth': {'accessToken': same_token}
            })
        )

        # Mock API response: 401
        mock_response_401 = Mock()
        mock_response_401.status_code = 401
        mock_get.return_value = mock_response_401

        # Create poller
        poller = ApiPoller(poll_interval=10)

        # Call _fetch_usage which should detect unchanged token
        result = poller._fetch_usage()

        # Verify no result (failed)
        assert result is None

        # Verify token is still the same
        assert poller.oauth_token == same_token

        # Verify requests.get was only called once (no retry)
        assert mock_get.call_count == 1

    @patch('claude_log_viewer.api_poller.subprocess.run')
    @patch('claude_log_viewer.api_poller.requests.get')
    def test_token_refresh_fails_when_new_token_also_invalid(self, mock_get, mock_subprocess):
        """Test that retry stops when refreshed token is also invalid."""
        # Mock token retrieval - different tokens
        initial_token = "sk-ant-oat01-initial-token"
        new_but_invalid_token = "sk-ant-oat01-new-but-invalid-token"

        keychain_responses = [
            # Initial token
            Mock(returncode=0, stdout=json.dumps({
                'claudeAiOauth': {'accessToken': initial_token}
            })),
            # New token (but still invalid)
            Mock(returncode=0, stdout=json.dumps({
                'claudeAiOauth': {'accessToken': new_but_invalid_token}
            }))
        ]
        mock_subprocess.side_effect = keychain_responses

        # Mock API responses: both 401
        mock_response_401 = Mock()
        mock_response_401.status_code = 401
        mock_get.return_value = mock_response_401

        # Create poller
        poller = ApiPoller(poll_interval=10)

        # Call _fetch_usage
        result = poller._fetch_usage()

        # Verify no result (failed)
        assert result is None

        # Verify token was updated
        assert poller.oauth_token == new_but_invalid_token

        # Verify requests.get was called twice (initial + retry)
        assert mock_get.call_count == 2

    @patch('claude_log_viewer.api_poller.subprocess.run')
    @patch('claude_log_viewer.api_poller.requests.get')
    def test_no_retry_on_successful_request(self, mock_get, mock_subprocess):
        """Test that no token refresh is attempted when request succeeds."""
        # Mock token retrieval
        token = "sk-ant-oat01-valid-token"
        mock_subprocess.return_value = Mock(
            returncode=0,
            stdout=json.dumps({
                'claudeAiOauth': {'accessToken': token}
            })
        )

        # Mock successful API response
        mock_response_200 = Mock()
        mock_response_200.status_code = 200
        mock_response_200.json.return_value = {
            'data': {
                'five_hour': {
                    'tokens_consumed': 1000,
                    'messages_count': 10,
                    'tokens_limit': 10000,
                    'messages_limit': 100,
                    'utilization': 10.0,
                    'reset_time': '2025-11-13T10:00:00Z'
                },
                'seven_day': {
                    'tokens_consumed': 5000,
                    'messages_count': 50,
                    'tokens_limit': 50000,
                    'messages_limit': 500,
                    'utilization': 10.0,
                    'reset_time': '2025-11-20T00:00:00Z'
                }
            }
        }
        mock_get.return_value = mock_response_200

        # Create poller
        poller = ApiPoller(poll_interval=10)

        # Call _fetch_usage
        result = poller._fetch_usage()

        # Verify successful result
        assert result is not None
        assert result['five_hour']['tokens_consumed'] == 1000

        # Verify requests.get was only called once (no retry)
        assert mock_get.call_count == 1

        # Verify token unchanged
        assert poller.oauth_token == token
