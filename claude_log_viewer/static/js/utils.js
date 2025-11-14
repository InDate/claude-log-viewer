// Utility functions

import { sessionColors } from './state.js';

// Generate consistent color for session ID
export function getSessionColor(sessionId) {
    if (!sessionId) return '#6e7681';

    if (!sessionColors[sessionId]) {
        // Generate unique color using hash of session ID
        let hash = 0;
        for (let i = 0; i < sessionId.length; i++) {
            hash = ((hash << 5) - hash) + sessionId.charCodeAt(i);
            hash = hash & hash; // Convert to 32bit integer
        }

        // Use hash to generate HSL color
        const hue = Math.abs(hash) % 360;
        const saturation = 70; // Keep consistent saturation
        const lightness = 50;  // Keep consistent lightness

        sessionColors[sessionId] = `hsl(${hue}, ${saturation}%, ${lightness}%)`;
    }

    return sessionColors[sessionId];
}

// Generate unique ID for an entry
export function getEntryId(entry) {
    return entry.uuid || `${entry.sessionId || 'unknown'}-${entry.timestamp || Date.now()}`;
}

// Unpack message structure into flat fields
export function unpackEntry(entry) {
    const unpacked = { ...entry };

    if (entry.message) {
        // Extract role
        if (entry.message.role) {
            unpacked.role = entry.message.role;
        }

        // Extract content - handle both string and array formats
        if (entry.message.content) {
            const content = entry.message.content;
            if (typeof content === 'string') {
                unpacked.content = content;
            } else if (Array.isArray(content)) {
                // For arrays, extract text from first text block
                const textBlock = content.find(c => c.type === 'text');
                if (textBlock) {
                    unpacked.content = textBlock.text;
                }
                // Store full content as well
                unpacked.content_full = content;
            }
        }

        // Extract other useful message fields
        if (entry.message.model) {
            unpacked.model = entry.message.model;
        }
        if (entry.message.stop_reason !== undefined) {
            unpacked.stop_reason = entry.message.stop_reason;
        }

        // Extract token usage from API
        if (entry.message.usage) {
            unpacked.input_tokens = entry.message.usage.input_tokens || 0;
            unpacked.output_tokens = entry.message.usage.output_tokens || 0;
        }
    }

    // Extract counted tokens from actual content
    if (entry.content_tokens !== undefined) {
        unpacked.content_tokens = entry.content_tokens;
    }

    return unpacked;
}

// Truncate long text to first and last sentence
export function truncateContent(text, maxLength = 200) {
    if (!text || text.length <= maxLength) {
        return text;
    }

    // Split into sentences (simple split on . ! ?)
    const sentences = text.match(/[^\.!\?]+[\.!\?]+/g) || [text];

    if (sentences.length <= 2) {
        return text;
    }

    const firstSentence = sentences[0].trim();
    const lastSentence = sentences[sentences.length - 1].trim();

    return `${firstSentence} [...] ${lastSentence}`;
}

// Format timestamp as relative time ("5 minutes ago", "2 hours ago", etc.)
export function formatRelativeTime(timestamp) {
    if (!timestamp) return '-';

    try {
        const date = new Date(timestamp);
        const now = new Date();
        const diffMs = now - date;
        const diffSeconds = Math.floor(diffMs / 1000);
        const diffMinutes = Math.floor(diffSeconds / 60);
        const diffHours = Math.floor(diffMinutes / 60);
        const diffDays = Math.floor(diffHours / 24);

        if (diffSeconds < 60) {
            return 'just now';
        } else if (diffMinutes < 60) {
            return `${diffMinutes}m ago`;
        } else if (diffHours < 24) {
            return `${diffHours}h ago`;
        } else if (diffDays < 7) {
            return `${diffDays}d ago`;
        } else {
            return date.toLocaleDateString();
        }
    } catch (e) {
        return '-';
    }
}

// Copy text to clipboard and show notification
export function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        showCopyNotification();
    }).catch(err => {
        console.error('Failed to copy:', err);
    });
}

export function showCopyNotification() {
    const notification = document.createElement('div');
    notification.className = 'copy-notification';
    notification.textContent = '✓ Copied to clipboard';
    document.body.appendChild(notification);

    setTimeout(() => {
        document.body.removeChild(notification);
    }, 2000);
}

// Format time remaining
export function formatTimeRemaining(resetTime) {
    const now = new Date();
    const reset = new Date(resetTime);
    const diff = reset - now;

    if (diff <= 0) return 'Resetting...';

    const hours = Math.floor(diff / 3600000);
    const mins = Math.floor((diff % 3600000) / 60000);

    if (hours > 24) {
        const days = Math.floor(hours / 24);
        const remainingHours = hours % 24;
        return `${days}d ${remainingHours}h`;
    } else if (hours > 0) {
        return `${hours}h ${mins}m`;
    } else {
        return `${mins}m`;
    }
}

// Get usage class based on percentage
export function getUsageClass(utilization) {
    if (utilization < 70) return 'low';
    if (utilization < 90) return 'medium';
    return 'high';
}

// Format large numbers
export function formatNumber(num) {
    if (num === null || num === undefined) {
        return '0';
    }
    if (num >= 1000000) {
        return (num / 1000000).toFixed(1) + 'M';
    } else if (num >= 1000) {
        return (num / 1000).toFixed(1) + 'K';
    }
    return num.toString();
}

// Format timestamp for display
export function formatTimestamp(timestamp) {
    if (!timestamp) return '-';

    try {
        const date = new Date(timestamp);
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMs / 3600000);
        const diffDays = Math.floor(diffMs / 86400000);

        if (diffMins < 1) return 'just now';
        if (diffMins < 60) return `${diffMins}m ago`;
        if (diffHours < 24) return `${diffHours}h ago`;
        if (diffDays < 7) return `${diffDays}d ago`;

        return date.toLocaleDateString();
    } catch (e) {
        return timestamp;
    }
}
