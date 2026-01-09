"""
Phase 5: Agent Planner/Router

Local-only planning service that converts operator goals into deterministic step plans.
Uses rules-based matching (no external LLM calls).
"""

import json
from typing import List, Dict, Any, Optional


class PlannerService:
    """
    Generates execution plans for agent runs.
    
    Given an operator goal + directive, produces a list of steps with:
    - step_type: task_call, decision, wait, notify
    - task_id: for task_call steps
    - inputs: step parameters
    
    Plans are deterministic and valid JSON.
    """
    
    # Task keywords for simple keyword matching
    TASK_KEYWORDS = {
        'log_triage': ['log', 'logs', 'triage', 'analyze', 'error', 'warning', 'event'],
        'gpu_report': ['gpu', 'nvidia', 'vram', 'utilization', 'memory', 'video', 'graphics'],
        'service_map': ['service', 'map', 'network', 'container', 'port', 'connection', 'expose'],
    }
    
    def plan(self, goal: str, directive) -> List[Dict[str, Any]]:
        """
        Generate a plan (list of steps) from an operator goal and directive.
        
        Args:
            goal: Operator's goal/prompt (e.g., "Analyze system logs and report GPU usage")
            directive: Directive instance with allowed tasks
        
        Returns:
            List of step dicts with: task_id, task_type, inputs
        
        Raises:
            ValueError: If goal is empty or directive is None
        """
        if not goal or not goal.strip():
            raise ValueError("Goal cannot be empty")
        if not directive:
            raise ValueError("Directive cannot be None")
        
        goal_lower = goal.lower()
        allowed_tasks = directive.task_list or []
        
        if not allowed_tasks:
            # Default to all three tasks if not specified
            allowed_tasks = ['log_triage', 'gpu_report', 'service_map']
        
        # Score each allowed task by keyword matches
        task_scores = {}
        for task_id in allowed_tasks:
            keywords = self.TASK_KEYWORDS.get(task_id, [])
            score = sum(1 for kw in keywords if kw in goal_lower)
            task_scores[task_id] = score
        
        # Sort by score (highest first)
        sorted_tasks = sorted(task_scores.items(), key=lambda x: x[1], reverse=True)
        
        # Build plan: include tasks with score > 0, or first task if all scored 0
        plan_tasks = []
        for task_id, score in sorted_tasks:
            if score > 0:
                plan_tasks.append(task_id)
        
        # If no keywords matched, use first allowed task as default
        if not plan_tasks:
            plan_tasks = [allowed_tasks[0]] if allowed_tasks else ['log_triage']
        
        # Limit to 3-5 tasks to keep agent runs bounded
        plan_tasks = plan_tasks[:5]
        
        # Build step list
        steps = []
        for idx, task_id in enumerate(plan_tasks):
            step = {
                'step_index': idx,
                'step_type': 'task_call',
                'task_id': task_id,
                'inputs': {
                    'goal': goal,
                    'task_config': directive.task_config or {},
                },
            }
            steps.append(step)
        
        # Add wait step between tasks (optional)
        if len(steps) > 1:
            # Insert a 2-second wait between tasks
            for i in range(len(steps) - 1, 0, -1):
                wait_step = {
                    'task_id': None,
                    'step_type': 'wait',
                    'step_index': i * 2,
                    'inputs': {'seconds': 2},
                }
                steps.insert(i * 2, wait_step)
        
        # Reindex steps
        for idx, step in enumerate(steps):
            step['step_index'] = idx
        
        return steps
    
    def validate_plan(self, plan: List[Dict[str, Any]], directive) -> bool:
        """
        Validate that a plan respects directive constraints.
        
        Checks:
        - All task_call steps use allowed tasks
        - Plan is not empty
        - Step types are valid
        
        Args:
            plan: Step list
            directive: Directive instance
        
        Returns:
            True if valid, False otherwise
        """
        if not plan or not isinstance(plan, list):
            return False
        
        allowed_tasks = directive.task_list or []
        valid_step_types = ['task_call', 'decision', 'wait', 'notify']
        
        for step in plan:
            if not isinstance(step, dict):
                return False
            
            step_type = step.get('step_type')
            if step_type not in valid_step_types:
                return False
            
            if step_type == 'task_call':
                task_id = step.get('task_id')
                if task_id and task_id not in allowed_tasks:
                    return False
        
        return True
