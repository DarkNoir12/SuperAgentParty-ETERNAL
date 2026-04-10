import asyncio
import json
import httpx
from typing import Dict, List, Optional, Any
from py.task_center import get_task_center, TaskStatus
from py.get_setting import load_settings, get_port

class SubAgentExecutor:
    """Sub-agent executor"""
    
    def __init__(self, workspace_dir: str, settings: Dict):
        self.workspace_dir = workspace_dir
        self.settings = settings
        self.port = get_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.chat_endpoint = f"{self.base_url}/v1/chat/completions"
        self.simple_chat_endpoint = f"{self.base_url}/simple_chat"
    
    async def execute_subtask(
        self,
        task_id: str,
        consensus_content: Optional[str] = None,
        max_iterations: int = 30
    ) -> Dict[str, Any]:
        """Main loop for executing a subtask"""
        task_center = await get_task_center(self.workspace_dir)
        task = await task_center.get_task(task_id)
        
        if not task:
            return {"success": False, "error": f"Task {task_id} not found"}
        
        # Mark task as started
        await task_center.update_task_progress(
            task_id=task_id, progress=0, status=TaskStatus.RUNNING
        )
        
        iteration = 0
        conversation_history = []
        assistant_only_history = task.context.get("history", [])
        
        system_prompt = self._build_system_prompt(task, consensus_content)
        conversation_history.append({"role": "system", "content": system_prompt})
        
        initial_user_msg = f"Please execute the following task:\n\n{task.description}\n\nRequirement: Once completed, organize and present the final result."
        conversation_history.append({"role": "user", "content": initial_user_msg})
        
        try:
            async with httpx.AsyncClient(timeout=600.0) as http_client:
                while iteration < max_iterations:
                    iteration += 1
                    current_progress = 10 + int((iteration / max_iterations) * 80)
                    print(f"[SubAgent] Task {task_id} - Iteration {iteration}")
                    
                    # 1. Call LLM (streaming, no flag passed internally)
                    assistant_response = await self._call_llm_stream_only(
                        http_client=http_client,
                        messages=conversation_history,
                        model='super-model',
                        task_id=task_id,
                        task_center=task_center,
                        base_progress=current_progress,
                        display_history=assistant_only_history
                    )
                    
                    conversation_history.append({
                        "role": "assistant",
                        "content": assistant_response
                    })
                    
                    # ⭐⭐⭐ Core logic: trust database state ⭐⭐⭐

                    # 2. Reload task state
                    # If finish_task was just called, the status here will be COMPLETED
                    latest_task = await task_center.get_task(task_id)
                    
                    if latest_task.status == TaskStatus.COMPLETED:
                        print(f"🚀 [SubAgent] Task {task_id} Status is COMPLETED. Finishing loop.")
                        return {
                            "success": True,
                            "task_id": task_id,
                            "result": latest_task.result,
                            "summary": "Task completed.",
                            "iterations": iteration
                        }

                    # 3. Only if status is not Completed, continue updating progress and check implicit completion
                    await task_center.update_task_progress(
                        task_id=task_id,
                        progress=current_progress,
                        status=TaskStatus.RUNNING,
                        context={"history": assistant_only_history, "current_iteration": iteration}
                    )

                    # 4. Implicit completion check (no tool called, but conversation indicates completion)
                    is_complete = await self._check_task_completion_smart(
                        task=task,
                        conversation_history=conversation_history,
                        http_client=http_client
                    )
                    
                    if is_complete:
                        print(f"⚡ [SubAgent] Implicit completion detected.")
                        last_response = assistant_response or "Task completed"
                        
                        await task_center.update_task_progress(
                            task_id=task_id,
                            progress=100,
                            status=TaskStatus.COMPLETED,
                            result=last_response,
                            context={"summary": last_response[:200] + "...", "history": assistant_only_history}
                        )
                        return {
                            "success": True,
                            "task_id": task_id,
                            "result": last_response,
                            "summary": last_response[:200] + "...",
                            "iterations": iteration
                        }
                    
                    conversation_history.append({
                        "role": "user",
                        "content": "Please continue executing the task. If all steps are complete, summarize and provide the final result."
                    })
                
                # ... timeout handling unchanged ...
                return {"success": False, "error": "Max iterations reached"}

        except Exception as e:
            # ... exception handling unchanged ...
            return {"success": False, "error": str(e)}

    async def _call_llm_stream_only(
        self, 
        http_client: httpx.AsyncClient, 
        messages: List[Dict], 
        model: str,
        task_id: str = None,
        task_center: Any = None,
        base_progress: int = 0,
        display_history: List[str] = None
    ) -> str:
        payload = {
            "messages": messages,
            "model": model,
            "stream": True, 
            "temperature": 0.5,
            "max_tokens": self.settings.get('max_tokens', 4000),
            "is_sub_agent": True,
            "disable_tools": ["create_subtask", "query_tasks_tool", "cancel_subtask"] 
        }

        full_content = ""
        current_text_buffer = ""
        tool_step_counter = 0

        try:
            async with http_client.stream("POST", self.chat_endpoint, json=payload, headers={"Content-Type": "application/json"}) as response:
                if response.status_code != 200:
                    raise Exception(f"API Error {response.status_code}")

                async for line in response.aiter_lines():
                    if not line.strip(): continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]": break
                        try:
                            chunk = json.loads(data_str)
                            if "error" in chunk or not chunk.get("choices"): continue
                            
                            delta = chunk["choices"][0].get("delta", {})

                            # 1. Accumulate text
                            content = delta.get("content")
                            if content:
                                full_content += content
                                current_text_buffer += content

                            # 2. Handle tools
                            tool_data = delta.get("tool_content")
                            if tool_data and task_center and task_id:
                                # Flush buffer
                                if current_text_buffer.strip():
                                    display_history.append(current_text_buffer.strip())
                                    current_text_buffer = ""
                                
                                tool_type = tool_data.get("type")
                                tool_title = str(tool_data.get("title", "Unknown")).strip()
                                
                                # ⭐⭐⭐ Key point: if finish_task, do NOT touch progress bar ⭐⭐⭐
                                if "finish_task" in tool_title:
                                    # finish_task already sets status to COMPLETED in task_tools.py
                                    # We must NOT call update_task_progress here, as it would overwrite back to RUNNING

                                    # Only log to display history, do not write to DB
                                    res_content = tool_data.get("content", "")
                                    display_history.append(f"✅ [{tool_title}]\nResult: {str(res_content)[:100]}...")
                                    continue 

                                # Normal progress updates for other tools
                                if tool_type in ["tool_result", "error"]:
                                    tool_step_counter += 1
                                    res_content = tool_data.get("content", "")
                                    icon = "✅" if tool_type == "tool_result" else "❌"
                                    
                                    short_res = str(res_content)[:300] + "..." if len(str(res_content)) > 300 else str(res_content)
                                    display_history.append(f"{icon} [{tool_title}]\nResult: {short_res}")
                                    
                                    micro_progress = min(base_progress + (tool_step_counter * 2), 99)
                                    
                                    # Only write to DB for non-finish_task tools
                                    await task_center.update_task_progress(
                                        task_id=task_id,
                                        progress=micro_progress,
                                        status=TaskStatus.RUNNING,
                                        context={"history": display_history}
                                    )

                        except: continue

        except Exception as e:
             raise Exception(f"Stream Failed: {str(e)}")

        if current_text_buffer.strip() and display_history is not None:
            display_history.append(current_text_buffer.strip())

        return full_content if full_content else "(Task executing...)"
    
    # ... (other helper methods like _build_system_prompt remain unchanged) ...
    def _build_system_prompt(self, task, consensus_content: Optional[str]) -> str:
        prompt = f"You are a professional task execution assistant.\n【Task Info】ID: {task.task_id} | Title: {task.title}\n【Requirements】Focus on completing the task, use available tools, and clearly indicate when finished."
        if consensus_content: prompt += f"\n\n【Consensus Spec】\n{consensus_content}\n"
        return prompt
    
    async def _check_task_completion_smart(self, task, conversation_history, http_client) -> bool:
        recent = self._get_recent_conversation(conversation_history)
        msgs = [{"role": "system", "content": "Determine if the task is complete. Reply only YES or NO."},
                {"role": "user", "content": f"Task: {task.description}\nRecent progress: {recent}\nIs it complete?"}]
        try:
            resp = await http_client.post(self.simple_chat_endpoint, json={"messages": msgs, "model": "super-model", "stream": False})
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip().upper().startswith("YES")
        except: pass
        return False
    
    async def _extract_final_result(self, task, conversation_history, http_client) -> Dict[str, str]:
        history_str = ""
        for msg in conversation_history:
            if msg["role"] in ["assistant", "user"]:
                content = msg["content"] if msg["content"] else "[Tool operation executed]"
                history_str += f"{msg['role']}: {content}\n"
        msgs = [{"role": "system", "content": "Extract the 【final execution result】 from the conversation history, keeping core content (such as reports, code, analysis results)."},
                {"role": "user", "content": f"Task objective: {task.description}\n\nConversation history:\n{history_str[-6000:]}\n\nPlease provide the final result:"}]
        full_res = "No result extracted"
        try:
            resp = await http_client.post(self.simple_chat_endpoint, json={"messages": msgs, "model": "super-model", "stream": False})
            if resp.status_code == 200: full_res = resp.json()["choices"][0]["message"]["content"].strip()
        except: 
            full_res = "\n".join([m["content"] for m in conversation_history if m["role"] == "assistant" and m["content"]])
        return {"full": full_res, "summary": full_res[:200].replace("\n", " ") + "..."}

    def _get_recent_conversation(self, conversation_history: List[Dict]) -> str:
        texts = []
        for msg in reversed(conversation_history[-5:]):
            texts.append(f"{msg['role']}: {str(msg.get('content'))[:200]}")
        return "\n".join(texts)

async def run_subtask_in_background(task_id: str, workspace_dir: str, settings: Dict, consensus_content: Optional[str] = None):
    executor = SubAgentExecutor(workspace_dir, settings)
    await executor.execute_subtask(task_id, consensus_content)