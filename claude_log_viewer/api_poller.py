"""
API Poller - Background service for polling Claude API usage data.

This module provides a background thread that polls the Claude API every 10 seconds
to retrieve usage data and trigger snapshot calculations automatically.

Architecture:
- Runs in a daemon background thread
- Polls Claude OAuth API endpoint every 10 seconds
- Detects usage changes and window resets
- Triggers snapshot_pipeline when usage changes
- Thread-safe shutdown mechanism

This replaces frontend-driven API polling with backend automation.
"""
import json
import logging
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import requests

from .snapshot_pipeline import trigger_snapshot_calculation


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Claude API configuration
CLAUDE_API_URL = "https://api.anthropic.com/api/oauth/usage"
DEFAULT_POLL_INTERVAL = 10  # seconds
REQUEST_TIMEOUT = 10  # seconds


class ApiPoller:
    """
    Background poller for Claude API usage data.

    This class manages a background thread that periodically polls the Claude API
    for usage statistics and triggers snapshot calculations when usage changes.

    Attributes:
        poll_interval: Seconds between API polls (default: 10)
        oauth_token: OAuth token for API authentication
        shutdown_event: Threading event for graceful shutdown
        thread: Background polling thread
        previous_usage: Last seen usage data for change detection
    """

    def __init__(self, poll_interval: int = DEFAULT_POLL_INTERVAL):
        """
        Initialize the API poller.

        Args:
            poll_interval: Seconds between polls (default: 10)

        Raises:
            ValueError: If OAuth token cannot be retrieved
        """
        self.poll_interval = poll_interval
        self.oauth_token = self._get_oauth_token()

        if not self.oauth_token:
            raise ValueError(
                "Failed to retrieve OAuth token from macOS Keychain. "
                "Please ensure Claude Code is properly authenticated."
            )

        self.shutdown_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.previous_usage: Optional[Dict[str, Any]] = None
        self.backoff_delay = 0  # Current backoff delay for error handling

        logger.info(f"ApiPoller initialized with {poll_interval}s poll interval")

    def start(self):
        """
        Start the background polling thread.

        This method is non-blocking and returns immediately after starting
        the daemon thread.
        """
        if self.thread and self.thread.is_alive():
            logger.warning("Poller already running")
            return

        self.shutdown_event.clear()
        self.thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.thread.start()

        logger.info("API poller started")

    def stop(self, timeout: int = 5):
        """
        Stop the background polling thread gracefully.

        Args:
            timeout: Maximum seconds to wait for thread to finish (default: 5)
        """
        if not self.thread or not self.thread.is_alive():
            logger.info("Poller not running")
            return

        logger.info("Stopping API poller...")
        self.shutdown_event.set()
        self.thread.join(timeout=timeout)

        if self.thread.is_alive():
            logger.warning(f"Poller thread did not stop within {timeout}s")
        else:
            logger.info("API poller stopped")

    def _poll_loop(self):
        """
        Main polling loop (runs in background thread).

        This method runs continuously until shutdown_event is set.
        Handles errors with exponential backoff.
        """
        logger.info("Polling loop started")

        while not self.shutdown_event.is_set():
            try:
                # Fetch usage data from API
                usage_data = self._fetch_usage()

                if usage_data:
                    # Reset backoff on successful fetch
                    self.backoff_delay = 0

                    # Check if usage changed
                    if self._has_usage_changed(usage_data):
                        logger.info("Usage change detected, triggering snapshot calculation")
                        self._handle_usage_update(usage_data)
                    else:
                        logger.debug("No usage change detected")

                    # Update previous usage
                    self.previous_usage = usage_data

            except requests.exceptions.RequestException as e:
                # Network error - use exponential backoff
                self._handle_network_error(e)

            except Exception as e:
                # Unexpected error - log and continue
                logger.error(f"Unexpected error in poll loop: {e}", exc_info=True)

            # Wait for next poll (or shutdown)
            # Use wait() instead of sleep() so we can interrupt on shutdown
            wait_time = self.poll_interval + self.backoff_delay
            if self.shutdown_event.wait(timeout=wait_time):
                break  # Shutdown requested

        logger.info("Polling loop exited")

    def _fetch_usage(self) -> Optional[Dict[str, Any]]:
        """
        Fetch usage data from Claude API.

        Returns:
            Usage data dictionary or None if request fails

        Raises:
            requests.exceptions.RequestException: On network errors
        """
        headers = {
            'Authorization': f'Bearer {self.oauth_token}',
            'Content-Type': 'application/json',
            'anthropic-beta': 'oauth-2025-04-20',
            'User-Agent': 'claude-code/2.0.32'
        }

        logger.debug(f"Fetching usage from {CLAUDE_API_URL}")

        response = requests.get(
            CLAUDE_API_URL,
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code == 200:
            data = response.json()
            logger.debug(f"Successfully fetched usage data")
            logger.debug(f"API response structure: {list(data.keys())}")

            # Transform API response to our format (handles both old and new formats)
            return self._transform_api_response(data)

        elif response.status_code == 401:
            logger.warning("OAuth token expired, attempting refresh from keychain...")

            # Attempt to refresh token from keychain
            new_token = self._get_oauth_token()

            if new_token and new_token != self.oauth_token:
                # Token changed - update and retry
                logger.info("New token detected in keychain, retrying API request...")
                self.oauth_token = new_token
                headers['Authorization'] = f'Bearer {self.oauth_token}'

                # Retry the request with new token
                retry_response = requests.get(
                    CLAUDE_API_URL,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT
                )

                if retry_response.status_code == 200:
                    logger.info("Token refresh successful - API request succeeded")
                    data = retry_response.json()
                    return self._transform_api_response(data)
                elif retry_response.status_code == 401:
                    logger.error("Token refresh failed - new token from keychain is also invalid")
                    return None
                else:
                    logger.warning(f"Token refresh succeeded but API returned status {retry_response.status_code}: {retry_response.text}")
                    return None
            elif new_token and new_token == self.oauth_token:
                logger.error("Token unchanged in keychain - token has not been refreshed by Claude Code")
                logger.error("Manual intervention required: Please restart Claude Code to get a fresh token")
                return None
            else:
                logger.error("Failed to read token from keychain - manual intervention required")
                return None

        else:
            logger.warning(f"API returned status {response.status_code}: {response.text}")
            return None

    def _transform_api_response(self, api_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform Claude API response to our internal format.

        Args:
            api_data: Raw API response (format: {'five_hour': {...}, 'seven_day': {...}})

        Returns:
            Transformed usage data with:
            - timestamp: ISO timestamp for this snapshot
            - five_hour: Usage data for 5-hour window
            - seven_day: Usage data for 7-day window

        Raises:
            ValueError: If API response is missing critical data or has invalid structure
        """
        five_hour = api_data.get('five_hour', {})
        seven_day = api_data.get('seven_day', {})

        if not five_hour and not seven_day:
            raise ValueError("API response missing both 'five_hour' and 'seven_day' data - cannot create snapshot")

        # Validate that we have at least utilization data
        five_hour_has_data = five_hour.get('utilization') is not None
        seven_day_has_data = seven_day.get('utilization') is not None

        if not five_hour_has_data and not seven_day_has_data:
            raise ValueError(
                "API response has no usable data (no utilization percentage) - "
                "refusing to create empty snapshot"
            )

        return {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'five_hour': {
                'tokens_consumed': five_hour.get('tokens_consumed', 0),
                'messages_count': five_hour.get('messages_count', 0),
                'tokens_limit': five_hour.get('tokens_limit', 100),
                'messages_limit': five_hour.get('messages_limit', 100),
                'pct': five_hour.get('utilization'),
                'reset': five_hour.get('resets_at', '')
            },
            'seven_day': {
                'tokens_consumed': seven_day.get('tokens_consumed', 0),
                'messages_count': seven_day.get('messages_count', 0),
                'tokens_limit': seven_day.get('tokens_limit', 100),
                'messages_limit': seven_day.get('messages_limit', 100),
                'pct': seven_day.get('utilization'),
                'reset': seven_day.get('resets_at', '')
            }
        }

    def _has_usage_changed(self, current_usage: Dict[str, Any]) -> bool:
        """
        Check if usage has changed since last poll.

        Detects:
        - Utilization percentage increases (new usage)
        - Utilization percentage decreases (window reset)

        Args:
            current_usage: Current usage data

        Returns:
            True if usage changed, False otherwise
        """
        if not self.previous_usage:
            # First poll - treat as change
            return True

        # Compare utilization percentages
        prev_5h_pct = self.previous_usage['five_hour']['pct']
        curr_5h_pct = current_usage['five_hour']['pct']

        prev_7d_pct = self.previous_usage['seven_day']['pct']
        curr_7d_pct = current_usage['seven_day']['pct']

        # Handle None values (API not providing utilization data)
        if curr_5h_pct is None and curr_7d_pct is None:
            # No percentage data available, can't determine change
            # Fall back to checking token counts
            prev_tokens = self.previous_usage['five_hour'].get('tokens_consumed', 0)
            curr_tokens = current_usage['five_hour'].get('tokens_consumed', 0)
            return curr_tokens != prev_tokens

        # Check for changes (increase or decrease)
        five_hour_changed = False
        seven_day_changed = False

        if prev_5h_pct is not None and curr_5h_pct is not None:
            five_hour_changed = abs(curr_5h_pct - prev_5h_pct) > 0.01  # 0.01% threshold
            if five_hour_changed:
                logger.debug(f"5-hour usage: {prev_5h_pct:.2f}% → {curr_5h_pct:.2f}%")

        if prev_7d_pct is not None and curr_7d_pct is not None:
            seven_day_changed = abs(curr_7d_pct - prev_7d_pct) > 0.01
            if seven_day_changed:
                logger.debug(f"7-day usage: {prev_7d_pct:.2f}% → {curr_7d_pct:.2f}%")

        return five_hour_changed or seven_day_changed

    def _handle_usage_update(self, usage_data: Dict[str, Any]):
        """
        Handle usage update by triggering snapshot pipeline.

        Args:
            usage_data: Current usage data
        """
        try:
            result = trigger_snapshot_calculation(usage_data)

            if result.get('success'):
                snapshot_id = result.get('snapshot_id')
                logger.info(f"Snapshot {snapshot_id} created and calculated successfully")
            else:
                error = result.get('error', 'Unknown error')
                logger.error(f"Snapshot calculation failed: {error}")

        except Exception as e:
            logger.error(f"Failed to trigger snapshot calculation: {e}", exc_info=True)

    def _handle_network_error(self, error: Exception):
        """
        Handle network errors with exponential backoff.

        Backoff sequence: 1s, 2s, 4s, 8s, 16s, 32s, 60s (max)

        Args:
            error: The network error that occurred
        """
        if self.backoff_delay == 0:
            self.backoff_delay = 1
        else:
            self.backoff_delay = min(self.backoff_delay * 2, 60)

        logger.warning(
            f"Network error: {error}. "
            f"Retrying in {self.backoff_delay}s (total delay: {self.poll_interval + self.backoff_delay}s)"
        )

    def _get_oauth_token(self) -> Optional[str]:
        """
        Retrieve OAuth token from macOS Keychain.

        Returns:
            OAuth token string or None if not found
        """
        try:
            result = subprocess.run(
                ['security', 'find-generic-password', '-s', 'Claude Code-credentials', '-w'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                credentials = result.stdout.strip()

                # Try to parse as JSON first
                try:
                    creds_json = json.loads(credentials)
                    token = creds_json.get('claudeAiOauth', {}).get('accessToken')
                    if token:
                        return token
                except json.JSONDecodeError:
                    # Not JSON - assume it's the raw token
                    return credentials

            logger.error(f"Failed to retrieve OAuth token: {result.stderr}")
            return None

        except Exception as e:
            logger.error(f"Error retrieving OAuth token: {e}")
            return None


if __name__ == '__main__':
    # Test the API poller
    print("Testing API Poller")
    print("=" * 80)
    print()

    try:
        # Create poller with 10-second interval
        poller = ApiPoller(poll_interval=10)
        print(f"✓ Poller created successfully")
        print(f"  Poll interval: {poller.poll_interval}s")
        print(f"  OAuth token: {'✓ Retrieved' if poller.oauth_token else '✗ Missing'}")
        print()

        # Start polling
        print("Starting poller (will run for 30 seconds)...")
        poller.start()

        # Let it run for 30 seconds
        time.sleep(30)

        # Stop polling
        print("\nStopping poller...")
        poller.stop()

        print("\n✓ Test complete!")

    except ValueError as e:
        print(f"✗ Failed to create poller: {e}")
        print("\nPlease ensure:")
        print("  1. Claude Code is installed")
        print("  2. You are logged in to Claude Code")
        print("  3. OAuth credentials are stored in macOS Keychain")

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        if 'poller' in locals():
            poller.stop()

    print()
    print("=" * 80)
