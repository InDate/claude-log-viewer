"""
Timeline Builder - Constructs conversation graph for visualization
"""

from typing import Dict, List, Any, Optional, Set
from datetime import datetime


class TimelineNode:
    """Represents a node in the conversation graph"""

    def __init__(self, entry: Dict[str, Any]):
        self.uuid = entry.get('uuid')
        self.parent_uuid = entry.get('parentUuid')
        self.logical_parent_uuid = entry.get('logicalParentUuid')
        self.session_id = entry.get('sessionId')
        self.agent_id = entry.get('agentId')
        self.is_sidechain = entry.get('isSidechain', False)
        self.type = entry.get('type')
        self.subtype = entry.get('subtype')
        self.timestamp = entry.get('timestamp')
        self.content = entry.get('content_display', '')[:200]  # Use pre-computed content_display
        self.role = entry.get('role')

        # Graph positioning (calculated later)
        self.lane = 0
        self.x_position = 0
        self.y_position = 0  # Chronological order position

        # Node classification
        self.is_compaction = (self.type == 'system' and
                             self.subtype == 'compact_boundary')
        self.is_session_start = (self.parent_uuid is None and
                                 self.logical_parent_uuid is not None)

        # Metadata
        self.compact_metadata = entry.get('compactMetadata', {})

        # Determine node display type
        self.display_type = self._get_display_type()
        self.branch_name = self._get_branch_name()

    def _get_display_type(self) -> str:
        """Get display type for the node"""
        if self.is_compaction:
            return 'compaction'
        if self.is_session_start:
            return 'session-link'
        if self.type == 'tool_result':
            return 'tool'
        if self.is_sidechain:
            return 'agent'
        if self.role == 'user':
            return 'user'
        if self.role == 'assistant':
            return 'assistant'
        return self.type or 'unknown'

    def _get_branch_name(self) -> str:
        """Get branch name for display"""
        if self.is_sidechain and self.agent_id:
            return f"Agent: {self.agent_id[:8]}"
        if self.is_session_start:
            return "Session Link"
        if self.is_compaction:
            return "Compaction"
        return "Main"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'uuid': self.uuid,
            'parentUuid': self.parent_uuid,
            'logicalParentUuid': self.logical_parent_uuid,
            'sessionId': self.session_id,
            'agentId': self.agent_id,
            'isSidechain': self.is_sidechain,
            'type': self.type,
            'subtype': self.subtype,
            'timestamp': self.timestamp,
            'content': self.content[:100] if self.content else '',  # Truncate for timeline
            'role': self.role,
            'lane': self.lane,
            'xPosition': self.x_position,
            'yPosition': self.y_position,
            'isCompaction': self.is_compaction,
            'isSessionStart': self.is_session_start,
            'compactMetadata': self.compact_metadata,
            'displayType': self.display_type,
            'branchName': self.branch_name
        }


class TimelineEdge:
    """Represents an edge (connection) between nodes"""

    def __init__(self, from_uuid: str, to_uuid: str, edge_type: str):
        self.from_uuid = from_uuid
        self.to_uuid = to_uuid
        self.type = edge_type  # 'parent', 'logical', 'sidechain'

    def to_dict(self) -> Dict[str, Any]:
        return {
            'from': self.from_uuid,
            'to': self.to_uuid,
            'type': self.type
        }


class TimelineBuilder:
    """Builds conversation timeline graph from entries"""

    def __init__(self, entries: List[Dict[str, Any]]):
        self.entries = entries
        self.nodes: Dict[str, TimelineNode] = {}
        self.edges: List[TimelineEdge] = []
        self.lanes: Dict[str, int] = {}  # session_id/agent_id -> lane number
        self.next_lane = 0
        self.structural_events: List[Dict[str, Any]] = []

    def build(self) -> Dict[str, Any]:
        """Build the complete timeline graph"""
        # Create nodes
        for entry in self.entries:
            if entry.get('uuid'):
                node = TimelineNode(entry)
                self.nodes[node.uuid] = node

        # Create edges
        self._create_edges()

        # Assign lanes
        self._assign_lanes()

        # Calculate positions
        self._calculate_positions()

        # Identify structural events and group messages
        self._identify_structural_events()

        # Return graph data with reversed structural events (newest first)
        return {
            'nodes': [node.to_dict() for node in self.nodes.values()],
            'edges': [edge.to_dict() for edge in self.edges],
            'lanes': self.lanes,
            'stats': self._calculate_stats(),
            'structuralEvents': list(reversed(self.structural_events))
        }

    def _create_edges(self):
        """Create edges between nodes"""
        for node in self.nodes.values():
            # Parent-child edge (same session)
            if node.parent_uuid and node.parent_uuid in self.nodes:
                edge_type = 'sidechain' if node.is_sidechain else 'parent'
                self.edges.append(TimelineEdge(node.parent_uuid, node.uuid, edge_type))

            # Logical parent edge (cross-session)
            if node.logical_parent_uuid and node.logical_parent_uuid in self.nodes:
                self.edges.append(TimelineEdge(
                    node.logical_parent_uuid,
                    node.uuid,
                    'logical'
                ))

    def _assign_lanes(self):
        """Assign vertical lanes to nodes for graph layout"""
        # Main session gets lane 0
        main_sessions = set()
        sidechain_sessions = set()

        for node in self.nodes.values():
            if node.is_sidechain:
                key = f"agent-{node.agent_id}"
                sidechain_sessions.add(key)
            else:
                main_sessions.add(node.session_id)

        # Assign lane 0 to main sessions
        for session_id in main_sessions:
            self.lanes[session_id] = 0

        # Assign lanes to sidechains
        for i, sidechain_key in enumerate(sorted(sidechain_sessions)):
            self.lanes[sidechain_key] = i + 1

        # Update node lanes
        for node in self.nodes.values():
            if node.is_sidechain:
                key = f"agent-{node.agent_id}"
                node.lane = self.lanes.get(key, 0)
            else:
                node.lane = self.lanes.get(node.session_id, 0)

    def _calculate_positions(self):
        """Calculate positions based on timestamps"""
        # Sort nodes by timestamp
        sorted_nodes = sorted(
            self.nodes.values(),
            key=lambda n: datetime.fromisoformat(n.timestamp.replace('Z', '+00:00'))
                         if n.timestamp else datetime.min
        )

        if not sorted_nodes:
            return

        # Calculate x positions (0-1000 range for normalization)
        first_time = datetime.fromisoformat(
            sorted_nodes[0].timestamp.replace('Z', '+00:00')
        )
        last_time = datetime.fromisoformat(
            sorted_nodes[-1].timestamp.replace('Z', '+00:00')
        )

        time_span = (last_time - first_time).total_seconds()
        if time_span == 0:
            time_span = 1

        # Assign y positions (chronological order) and x positions (time-based)
        for i, node in enumerate(sorted_nodes):
            node.y_position = i  # Chronological order (0, 1, 2, ...)
            node_time = datetime.fromisoformat(
                node.timestamp.replace('Z', '+00:00')
            )
            elapsed = (node_time - first_time).total_seconds()
            node.x_position = (elapsed / time_span) * 1000

    def _identify_structural_events(self):
        """Identify handover messages, notable events, and create chronological flow"""
        # Sort nodes by y_position (chronological order)
        sorted_nodes = sorted(self.nodes.values(), key=lambda n: n.y_position)

        # Build agent start/end mappings
        agent_info = self._build_agent_info(sorted_nodes)

        # Identify handover points
        handover_nodes = set()

        # Add branch trigger messages (last main message before each agent starts)
        for agent_id, info in agent_info.items():
            trigger = self._find_branch_trigger(info['start_node'], sorted_nodes)
            if trigger:
                handover_nodes.add(trigger.uuid)

        # Add agent start/end nodes (these are always handovers)
        for agent_id, info in agent_info.items():
            handover_nodes.add(info['start_node'].uuid)
            if info['end_node']:
                handover_nodes.add(info['end_node'].uuid)

        # Add merge response messages (first main message after each agent ends)
        for agent_id, info in agent_info.items():
            if info['end_node']:
                response = self._find_merge_response(info['end_node'], sorted_nodes)
                if response:
                    handover_nodes.add(response.uuid)

        # Create chronological events with handovers and context groups
        current_lane = None
        current_group = []
        tool_count = 0

        for node in sorted_nodes:
            is_handover = node.uuid in handover_nodes

            # Check if this is a notable event (todo/plan)
            notable_event = self._get_notable_event(node)

            # Lane change, handover, or notable event triggers group emission
            if (current_lane is not None and node.lane != current_lane) or is_handover or notable_event:
                if current_group:
                    self._emit_context_group(current_group, tool_count, current_lane)
                    current_group = []
                    tool_count = 0

            current_lane = node.lane

            if is_handover:
                # Emit handover message (full content)
                event_type = self._get_handover_type(node, agent_info)
                self.structural_events.append({
                    'type': 'handover',
                    'handoverType': event_type,
                    'lane': node.lane,
                    'node': node.uuid,
                    'yPosition': node.y_position,
                    'agentId': node.agent_id if node.is_sidechain else None,
                    'branchName': node.branch_name,
                    'content': node.content,
                    'isParallel': self._is_parallel_at_time(node, agent_info)
                })
            elif notable_event:
                # Emit notable event (todo/plan)
                self.structural_events.append(notable_event)
            else:
                # Regular message - accumulate for context
                current_group.append(node)
                if node.type == 'tool_result':
                    tool_count += 1

        # Emit final group
        if current_group:
            self._emit_context_group(current_group, tool_count, current_lane)

    def _build_agent_info(self, sorted_nodes):
        """Build mapping of agent_id -> {start_node, end_node}"""
        agent_info = {}
        for node in sorted_nodes:
            if node.is_sidechain and node.agent_id:
                if node.agent_id not in agent_info:
                    agent_info[node.agent_id] = {'start_node': node, 'end_node': None, 'nodes': []}
                agent_info[node.agent_id]['nodes'].append(node)
                agent_info[node.agent_id]['end_node'] = node  # Last one wins
        return agent_info

    def _find_branch_trigger(self, agent_start_node, sorted_nodes):
        """Find the main lane message that triggered this agent"""
        # Look for the parent of the agent's first node
        for edge in self.edges:
            if edge.to_uuid == agent_start_node.uuid and edge.from_uuid in self.nodes:
                parent = self.nodes[edge.from_uuid]
                if parent.lane == 0:  # Main lane
                    return parent
        return None

    def _find_merge_response(self, agent_end_node, sorted_nodes):
        """Find the first main lane message after agent completes"""
        # Look for child of agent's last node in main lane
        for edge in self.edges:
            if edge.from_uuid == agent_end_node.uuid and edge.to_uuid in self.nodes:
                child = self.nodes[edge.to_uuid]
                if child.lane == 0:  # Main lane
                    return child
        return None

    def _get_handover_type(self, node, agent_info):
        """Determine what type of handover this is"""
        if node.is_sidechain:
            # Check if it's agent start or end
            for agent_id, info in agent_info.items():
                if info['start_node'].uuid == node.uuid:
                    return 'agent_start'
                if info['end_node'] and info['end_node'].uuid == node.uuid:
                    return 'agent_end'
        else:
            # Check if it triggers an agent
            for edge in self.edges:
                if edge.from_uuid == node.uuid and edge.to_uuid in self.nodes:
                    child = self.nodes[edge.to_uuid]
                    if child.lane != node.lane:
                        return 'branch_trigger'
            # Check if it's a merge response
            for edge in self.edges:
                if edge.to_uuid == node.uuid and edge.from_uuid in self.nodes:
                    parent = self.nodes[edge.from_uuid]
                    if parent.lane != node.lane and parent.is_sidechain:
                        return 'merge_response'
        return 'unknown'

    def _is_parallel_at_time(self, node, agent_info):
        """Check if multiple agents are active at this node's timestamp"""
        active_agents = 0
        for agent_id, info in agent_info.items():
            start_y = info['start_node'].y_position
            end_y = info['end_node'].y_position if info['end_node'] else float('inf')
            if start_y <= node.y_position <= end_y:
                active_agents += 1
        return active_agents > 1

    def _get_notable_event(self, node):
        """Check if node is a notable event (todo/plan) and return event dict"""
        # Get the original entry to access tool_items
        entry = next((e for e in self.entries if e.get('uuid') == node.uuid), None)
        if not entry:
            return None

        tool_items = entry.get('tool_items', {})
        tool_uses = tool_items.get('tool_uses', [])

        for tool_use in tool_uses:
            tool_name = tool_use.get('name', '')
            tool_input = tool_use.get('input', {})
            tool_use_id = tool_use.get('id', '')

            # TodoWrite events
            if tool_name == 'TodoWrite':
                # Find the child entry (user message with tool result) that contains toolUseResult
                tool_result_entry = next((e for e in self.entries
                                         if e.get('parentUuid') == entry.get('uuid')
                                         and e.get('type') == 'user'
                                         and 'toolUseResult' in e), None)

                tool_use_result = None
                if tool_result_entry:
                    tool_use_result = tool_result_entry.get('toolUseResult', {})

                return self._create_todo_event(node, tool_input, tool_use_result)

            # ExitPlanMode events (plan creation)
            elif tool_name == 'ExitPlanMode':
                plan = tool_input.get('plan', '')
                return self._create_plan_event(node, plan)

        return None

    def _create_todo_event(self, node, tool_input, tool_use_result):
        """Create a notable event for todo changes using delta from tool results"""
        todos = tool_input.get('todos', [])
        if not todos:
            return None

        # Get old/new todos from toolUseResult (from the tool_result entry)
        old_todos = []
        new_todos = todos

        if tool_use_result:
            old_todos = tool_use_result.get('oldTodos', [])
            new_todos = tool_use_result.get('newTodos', todos)

        # Build a map of old todos by content for comparison
        old_todo_map = {t.get('content'): t for t in old_todos}

        # Find what changed
        parts = []
        newly_completed = []
        newly_started = []
        newly_added = []
        newly_added_and_started = []

        for todo in new_todos:
            content = todo.get('content')
            new_status = todo.get('status')
            old_todo = old_todo_map.get(content)

            if old_todo:
                old_status = old_todo.get('status')
                # Status changed
                if old_status != new_status:
                    if new_status == 'completed':
                        newly_completed.append(content)
                    elif new_status == 'in_progress' and old_status != 'in_progress':
                        newly_started.append(content)
            else:
                # New todo created - show regardless of initial status
                if new_status == 'in_progress':
                    newly_added_and_started.append(content)
                else:  # pending or any other status
                    newly_added.append(content)

        # Build minimal summary showing only deltas (no icons)
        if newly_completed:
            for content in newly_completed[:2]:  # Show max 2
                parts.append(f"Completed: {content}")
            if len(newly_completed) > 2:
                parts.append(f"and {len(newly_completed) - 2} more completed")

        if newly_started:
            for content in newly_started[:2]:  # Show max 2
                parts.append(f"Started: {content}")
            if len(newly_started) > 2:
                parts.append(f"and {len(newly_started) - 2} more started")

        if newly_added_and_started:
            for content in newly_added_and_started[:2]:  # Show max 2
                parts.append(f"Added and started: {content}")
            if len(newly_added_and_started) > 2:
                parts.append(f"and {len(newly_added_and_started) - 2} more added and started")

        if newly_added:
            for content in newly_added[:4]:  # Show max 4
                parts.append(f"Added: {content}")
            if len(newly_added) > 4:
                parts.append(f"and {len(newly_added) - 4} more added")

        summary = '\n'.join(parts) if parts else "Updated todos"

        return {
            'type': 'notable_event',
            'eventType': 'todo',
            'lane': node.lane,
            'node': node.uuid,
            'yPosition': node.y_position,
            'summary': summary,
            'details': todos
        }

    def _create_plan_event(self, node, plan_text):
        """Create a notable event for plan creation"""
        if not plan_text:
            return None

        # Extract plan title (first line, typically a markdown header)
        lines = plan_text.split('\n')
        title = lines[0].strip('#').strip() if lines else "Plan created"

        return {
            'type': 'notable_event',
            'eventType': 'plan',
            'lane': node.lane,
            'node': node.uuid,
            'yPosition': node.y_position,
            'summary': title,  # Just the title, no icon
            'details': plan_text[:200]  # First 200 chars
        }

    def _emit_context_group(self, nodes, tool_count, lane):
        """Emit a context group (collapsed messages between handovers)"""
        if not nodes:
            return

        # Calculate metadata
        first_ts = nodes[0].timestamp
        last_ts = nodes[-1].timestamp
        user_count = sum(1 for n in nodes if n.role == 'user')
        assistant_count = sum(1 for n in nodes if n.role == 'assistant')

        self.structural_events.append({
            'type': 'context_group',
            'lane': lane,
            'count': len(nodes),
            'toolCount': tool_count,
            'userCount': user_count,
            'assistantCount': assistant_count,
            'nodes': [n.uuid for n in nodes],
            'yPosition': nodes[0].y_position,
            'firstTimestamp': first_ts,
            'lastTimestamp': last_ts
        })

    def _has_branch_children(self, node: TimelineNode) -> bool:
        """Check if node has children in different lanes"""
        for edge in self.edges:
            if edge.from_uuid == node.uuid and edge.to_uuid in self.nodes:
                child = self.nodes[edge.to_uuid]
                if child.lane != node.lane:
                    return True
        return False

    def _has_merge_edge(self, node: TimelineNode) -> bool:
        """Check if node has edge back to main lane"""
        for edge in self.edges:
            if edge.from_uuid == node.uuid and edge.to_uuid in self.nodes:
                child = self.nodes[edge.to_uuid]
                if child.lane == 0 and node.lane != 0:  # Merging back to main
                    return True
        return False

    def _calculate_stats(self) -> Dict[str, Any]:
        """Calculate timeline statistics"""
        compaction_count = sum(1 for n in self.nodes.values() if n.is_compaction)
        session_count = len(set(n.session_id for n in self.nodes.values() if not n.is_sidechain))
        agent_count = len(set(n.agent_id for n in self.nodes.values() if n.is_sidechain and n.agent_id))

        return {
            'totalNodes': len(self.nodes),
            'totalEdges': len(self.edges),
            'compactionCount': compaction_count,
            'sessionCount': session_count,
            'agentBranchCount': agent_count,
            'laneCount': len(self.lanes)
        }


def build_timeline(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Convenience function to build timeline graph"""
    builder = TimelineBuilder(entries)
    return builder.build()
