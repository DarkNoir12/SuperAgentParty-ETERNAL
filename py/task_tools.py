"""Task management tools for the main agent"""
import asyncio
from typing import Optional
from py.task_center import get_task_center, TaskStatus
from py.sub_agent import run_subtask_in_background

# --- Tool Definitions ---

create_subtask_tool = {
    "type": "function",
    "function": {
        "name": "create_subtask",
        "description": """Create a subtask and execute it asynchronously in the background.

⚠️ Usage scenarios:
- Split large tasks into multiple independent subtasks for parallel execution
- Execute time-consuming tasks (e.g., batch processing, deep research)
- Delegate specialized domain problems to dedicated sub-agents

✅ Features:
- Asynchronous execution, does not block main conversation
- Auto-saves progress, recoverable after restart
- Real-time status can be viewed via query_task_progress

📝 Returns: Subtask ID for tracking progress

⚠️ Notes:
- Each subtask has an independent conversation context
- Subtasks cannot access main conversation history (unless explicitly stated in description)
- It is recommended to provide complete background information and clear completion criteria in the description
- Unless requested by the user, do not proactively query subtask progress after creation; the client UI will automatically display current progress and results to the user""",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Brief title for the subtask (recommended under 50 characters)"
                },
                "description": {
                    "type": "string",
                    "description": """Detailed description of the subtask, must include:
1. Task objective: Specific expected result
2. Background information: Necessary context and prerequisite knowledge
3. Completion criteria: How to determine the task is complete
4. Constraints: Rules or limitations to follow"""
                },
                "agent_type": {
                    "type": "string",
                    "description": "Agent type to use (currently fixed as 'default')",
                    "default": "default"
                }
            },
            "required": ["title", "description"]
        }
    }
}

query_tasks_tool = {
    "type": "function",
    "function": {
        "name": "query_task_progress",
        "description": "Query task progress. Supports precise query by task ID, or batch query by parent task and status.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": { 
                    "type": "string",
                    "description": "Optional: Specify task ID for precise query"
                },
                "parent_task_id": {
                    "type": "string",
                    "description": "Optional: Query all subtasks under a specific parent task"
                },
                "status": {
                    "type": "string",
                    "description": "Optional: Filter by specific status",
                    "enum": ["pending", "running", "completed", "failed", "cancelled"]
                },
                "verbose": {
                    "type": "boolean",
                    "description": "Set to true to view full results of completed tasks",
                    "default": False
                }
            }
        }
    }
}

cancel_subtask_tool = {
    "type": "function",
    "function": {
        "name": "cancel_subtask",
        "description": "Cancel a running or pending subtask.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "ID of the task to cancel"
                }
            },
            "required": ["task_id"]
        }
    }
}

# ⭐ New: finish_task_tool
# Note: This tool should only be provided to sub-agents (SubAgent)
finish_task_tool = {
    "type": "function",
    "function": {
        "name": "finish_task",
        "description": """✅ Task completion confirmation tool.
When all task objectives are met, you 【must】 call this tool to formally end the task.

⚠️ Key rules:
1. Only calling this tool will truly change the task status to COMPLETED.
2. After calling, place your final deliverable (code, report, conclusion) in the result parameter.
3. After calling this tool, the current conversation flow will terminate immediately — do not output any additional content.

❌ Do NOT just say "I'm done" in conversation — you must call this tool!""",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "ID of the current task"
                },
                "result": {
                    "type": "string",
                    "description": "Final task output report. This will be shown as the official result to the parent agent or user. Ensure content is complete and well-formatted (Markdown supported)."
                }
            },
            "required": ["task_id", "result"]
        }
    }
}

# --- Tool Implementations ---

async def create_subtask(
    title: str,
    description: str,
    agent_type: str = "default",
    workspace_dir: str = None,
    settings: dict = None,
    parent_task_id: Optional[str] = None,
    consensus_content: Optional[str] = None
) -> str:
    """Create and start a subtask"""
    try:
        task_center = await get_task_center(workspace_dir)
        
        # Create task
        task = await task_center.create_task(
            title=title,
            description=description,
            parent_task_id=parent_task_id,
            agent_type=agent_type
        )
        
        # Execute asynchronously in background
        asyncio.create_task(
            run_subtask_in_background(
                task_id=task.task_id,
                workspace_dir=workspace_dir,
                settings=settings, 
                consensus_content=consensus_content
            )
        )
    except Exception as e:
        return f"❌ Subtask creation failed: {str(e)}"
    
    return f"✅ Subtask created and executing\n\nTask ID: {task.task_id}\nTitle: {task.title}\nPlease do not proactively query task progress; the client UI will automatically display current progress and results to the user"

async def query_task_progress(
    workspace_dir: str,
    task_id: Optional[str] = None,  # New: accept task_id
    parent_task_id: Optional[str] = None,
    status: Optional[str] = None,
    verbose: bool = False
) -> str:
    """Query task progress - supports single task precise query and list query"""
    try:
        from py.task_center import get_task_center, TaskStatus
        
        task_center = await get_task_center(workspace_dir)
        status_enum = TaskStatus(status) if status else None
        
        tasks = []

        # 👉 Optimization 1: If task_id exists, prioritize precise lookup, ignore status filter
        if task_id:
            single_task = await task_center.get_task(task_id)
            if single_task:
                tasks = [single_task]
            else:
                return f"❌ Task with ID {task_id} not found, please check the ID."

        # 👉 Optimization 2: If no task_id, perform list search and filtering
        else:
            status_enum = TaskStatus(status) if status else None
            tasks = await task_center.list_tasks(
                parent_task_id=parent_task_id,
                status=status_enum
            )
        
        if not tasks:
            return "📋 Task center has no relevant tasks at the moment."

        # Build output
        result_lines = [f"📋 Task Center Status ({len(tasks)} tasks total)"]
        if verbose:
            result_lines.append("📢 [Detail Mode] ON: Showing full results...")
        result_lines.append("-" * 30)
        
        for task in tasks:
            icon = "✅" if task.status == TaskStatus.COMPLETED else "🔄" if task.status == TaskStatus.RUNNING else "⏳"
            result_lines.append(f"{icon} [{task.task_id}] {task.title}")
            result_lines.append(f"   Status: {task.status.value.upper()} | Progress: {task.progress}%")
            
            history = task.context.get("history", [])
            
            # Running
            if task.status == TaskStatus.RUNNING:
                if history:
                    result_lines.append(f"   Execution update: {history[-1][:100]}...")
                if verbose and history:
                    result_lines.append("   📜 Completed steps:")
                    for i, step in enumerate(history, 1):
                        result_lines.append(f"     {i}. {step[:200]}...")

            # Completed
            elif task.status == TaskStatus.COMPLETED:
                if verbose:
                    # ✅ If verbose=True, force show full result
                    result_content = task.result if task.result else "(no result content)"
                    result_lines.append(f"   🎯 Final complete output:\n{result_content}\n")

                    # Optional: Show intermediate process
                    if history:
                        result_lines.append("   📜 Execution process trace (last 3 steps):")
                        for i, step in enumerate(history[-3:], 1):
                            result_lines.append(f"     ... {step[:100]} ...")
                else:
                    summary = task.context.get('summary') or (task.result[:150] + "..." if task.result else "No result content")
                    result_lines.append(f"   📝 Result summary: {summary}")
                    result_lines.append(f"   💡 (Tip: use verbose=true to view the full report)")

            elif task.status == TaskStatus.FAILED:
                result_lines.append(f"   ❌ Error: {task.error}")

            result_lines.append("") 
    except Exception as e:
        return f"❌ Failed to query task progress: {str(e)}"

    return "\n".join(result_lines)

async def cancel_subtask(workspace_dir: str, task_id: str) -> str:
    """Cancel subtask"""
    try:
        task_center = await get_task_center(workspace_dir)
        success = await task_center.cancel_task(task_id)
    except Exception as e:
        return f"❌ Failed to cancel task: {str(e)}"
    return f"✅ Task {task_id} cancelled" if success else f"❌ Failed to cancel task {task_id}"

# ⭐ New implementation: finish_task
async def finish_task(
    workspace_dir: str,
    task_id: str,
    result: str
) -> str:
    try:
        """Sub-agent calls this function to mark task as completed"""
        task_center = await get_task_center(workspace_dir)
        
        # Force update to COMPLETED, progress 100, and save final result
        success = await task_center.update_task_progress(
            task_id=task_id,
            progress=100,
            status=TaskStatus.COMPLETED,
            result=result
        )
    except Exception as e:
        return f"❌ Failed to mark task as completed: {str(e)}"

    if success:
        return f"🎉 Task {task_id} has been successfully marked as complete! Result saved. Please stop further operations."
    else:
        return f"❌ Task {task_id} status update failed (possibly incorrect task ID)."