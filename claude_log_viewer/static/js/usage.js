// Usage tracking and display

import { formatTimeRemaining, getUsageClass, formatNumber, formatRelativeTime } from './utils.js';
import { setUsageRefreshInterval } from './state.js';

// Fetch and render usage data
export async function loadUsageData() {
    try {
        const response = await fetch('/api/usage');
        const data = await response.json();

        if (data.error) {
            renderUsageError(data.error);
            return;
        }

        renderUsageData(data);
    } catch (error) {
        console.error('Error loading usage data:', error);
        renderUsageError(error.message);
    }
}

function renderUsageError(errorMsg) {
    const container = document.getElementById('usageGrid');
    container.innerHTML = `<div class="usage-error">Failed to load usage data: ${errorMsg}</div>`;
}

function renderUsageData(data) {
    const container = document.getElementById('usageGrid');
    container.innerHTML = '';

    // 5-hour window
    if (data.five_hour) {
        const item = document.createElement('div');
        item.className = 'usage-item clickable';
        item.style.cursor = 'pointer';

        const utilization = data.five_hour.utilization || 0;
        const usageClass = getUsageClass(utilization);

        item.innerHTML = `
            <div class="usage-info">
                <div class="usage-label">5-Hour Window</div>
                <div class="usage-time">Resets in ${formatTimeRemaining(data.five_hour.resets_at)}</div>
            </div>
            <div class="usage-value ${usageClass}">${utilization.toFixed(1)}%</div>
        `;

        item.addEventListener('click', () => showUsageHistory());

        container.appendChild(item);
    }

    // 7-day window
    if (data.seven_day) {
        const item = document.createElement('div');
        item.className = 'usage-item clickable';
        item.style.cursor = 'pointer';

        const utilization = data.seven_day.utilization || 0;
        const usageClass = getUsageClass(utilization);

        item.innerHTML = `
            <div class="usage-info">
                <div class="usage-label">7-Day Window</div>
                <div class="usage-time">Resets in ${formatTimeRemaining(data.seven_day.resets_at)}</div>
            </div>
            <div class="usage-value ${usageClass}">${utilization.toFixed(1)}%</div>
        `;

        item.addEventListener('click', () => showUsageHistory());

        container.appendChild(item);
    }
}

// Show usage history modal with all snapshots
async function showUsageHistory() {
    const modal = document.getElementById('contentModal');
    const modalContent = document.getElementById('modalContent');

    try {
        // Fetch all snapshots
        const now = new Date().toISOString();
        const oneWeekAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();

        const response = await fetch(`/api/usage-snapshots?start=${oneWeekAgo}&end=${now}`);
        const data = await response.json();

        if (data.error) {
            modalContent.innerHTML = `<div style="color: #f48771;">Error loading snapshots: ${data.error}</div>`;
            modal.classList.add('active');
            return;
        }

        const snapshots = data.snapshots || [];

        if (snapshots.length === 0) {
            modalContent.innerHTML = `
                <h2>Usage History</h2>
                <p style="color: #9d9d9d; margin-top: 20px;">No usage snapshots recorded yet.</p>
                <p style="color: #9d9d9d; margin-top: 10px;">Snapshots are automatically created whenever your 5-hour or 7-day usage increases.</p>
            `;
        } else {
            // Build table
            let tableHTML = `
                <h2>Usage History (${snapshots.length} snapshots)</h2>
                <div style="overflow-x: auto; margin-top: 20px;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <thead>
                            <tr style="border-bottom: 2px solid #3e3e42;">
                                <th style="padding: 10px; text-align: left; color: #9d9d9d;">When</th>
                                <th style="padding: 10px; text-align: left; color: #9d9d9d;">Timestamp</th>
                                <th style="padding: 10px; text-align: right; color: #9d9d9d;">5h Util</th>
                                <th style="padding: 10px; text-align: right; color: #9d9d9d;">5h Tokens</th>
                                <th style="padding: 10px; text-align: right; color: #9d9d9d;">5h Messages</th>
                                <th style="padding: 10px; text-align: right; color: #9d9d9d;">7d Util</th>
                                <th style="padding: 10px; text-align: right; color: #9d9d9d;">7d Tokens</th>
                                <th style="padding: 10px; text-align: right; color: #9d9d9d;">7d Messages</th>
                            </tr>
                        </thead>
                        <tbody>
            `;

            snapshots.forEach(snapshot => {
                const timestamp = new Date(snapshot.timestamp).toLocaleString();
                const when = formatRelativeTime(snapshot.timestamp);
                const fiveHourPct = (snapshot.five_hour_pct || 0).toFixed(1);
                const sevenDayPct = (snapshot.seven_day_pct || 0).toFixed(1);
                const fiveHourClass = getUsageClass(snapshot.five_hour_pct || 0);
                const sevenDayClass = getUsageClass(snapshot.seven_day_pct || 0);

                // Format token/message data with "total (+delta)" format
                const formatValue = (val) => val !== null && val !== undefined ? formatNumber(val) : '—';
                const formatWithDelta = (total, delta) => {
                    if (total === null || total === undefined) return '—';
                    if (delta === null || delta === undefined) return formatValue(total);
                    return `${formatValue(total)} (+${formatValue(delta)})`;
                };

                const fiveHourTokens = formatWithDelta(snapshot.five_hour_tokens_total, snapshot.five_hour_tokens_consumed);
                const fiveHourMessages = formatWithDelta(snapshot.five_hour_messages_total, snapshot.five_hour_messages_count);
                const sevenDayTokens = formatWithDelta(snapshot.seven_day_tokens_total, snapshot.seven_day_tokens_consumed);
                const sevenDayMessages = formatWithDelta(snapshot.seven_day_messages_total, snapshot.seven_day_messages_count);

                tableHTML += `
                    <tr style="border-bottom: 1px solid #2d2d30;">
                        <td style="padding: 10px; color: #9d9d9d; font-weight: 500;">${when}</td>
                        <td style="padding: 10px; color: #7d7d7d; font-size: 11px;">${timestamp}</td>
                        <td style="padding: 10px; text-align: right;">
                            <span class="usage-value ${fiveHourClass}" style="padding: 2px 6px; font-size: 11px;">${fiveHourPct}%</span>
                        </td>
                        <td style="padding: 10px; text-align: right; color: #8d8d8d; font-size: 11px;">${fiveHourTokens}</td>
                        <td style="padding: 10px; text-align: right; color: #8d8d8d; font-size: 11px;">${fiveHourMessages}</td>
                        <td style="padding: 10px; text-align: right;">
                            <span class="usage-value ${sevenDayClass}" style="padding: 2px 6px; font-size: 11px;">${sevenDayPct}%</span>
                        </td>
                        <td style="padding: 10px; text-align: right; color: #8d8d8d; font-size: 11px;">${sevenDayTokens}</td>
                        <td style="padding: 10px; text-align: right; color: #8d8d8d; font-size: 11px;">${sevenDayMessages}</td>
                    </tr>
                `;
            });

            tableHTML += `
                        </tbody>
                    </table>
                </div>
            `;

            modalContent.innerHTML = tableHTML;
        }

        modal.classList.add('active');
    } catch (error) {
        console.error('Error fetching usage history:', error);
        modalContent.innerHTML = `<div style="color: #f48771;">Failed to load usage history: ${error.message}</div>`;
        modal.classList.add('active');
    }
}

export function startUsagePolling() {
    // Initial load
    loadUsageData();

    // Poll every 60 seconds
    const interval = setInterval(loadUsageData, 60000);
    setUsageRefreshInterval(interval);
}
