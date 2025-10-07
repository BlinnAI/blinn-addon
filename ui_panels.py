import os
import bpy
from bpy.types import Operator
import json
import requests
import asyncio
import queue
import textwrap
import threading
import tempfile
import logging
from datetime import datetime
from .utils import clean_script

bk_logger = logging.getLogger(__name__)


class BLINN_CHAT_OT_execute_script(Operator):
    bl_idname = "blinnai.execute_script"
    bl_label = "Execute AI Script"
    bl_description = "Execute the AI-generated script"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        scene = context.scene
        chat_props = scene.blinnai_chat_props

        if not scene.blinnai_messages:
            return {"FINISHED"}
        
        message = scene.blinnai_messages[-1]
        if len(message.script) == 0:
            return {"FINISHED"}
        
        temp_file_path = None

        try:
            script = clean_script(message.script)
            chat_props.is_executing_script = True
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as temp_file:
                temp_file.write(script)
                temp_file_path = temp_file.name
            bpy.ops.script.python_file_run(filepath=temp_file_path)
        except Exception as e:
            self.report({'ERROR'}, f"Script execution failed: {str(e)}")
        finally:
            chat_props.is_executing_script = False
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except Exception as e:
                    print(f"Failed to delete temp file: {str(e)}")
        
        return {"FINISHED"}

class BLINN_CHAT_OT_send_message(Operator):
    bl_idname = "blinnai.send_message"
    bl_label = "Send Message"
    bl_description = "Send the chat message"
    bl_options = {"REGISTER", "UNDO"}

    _timer = None
    _loop = None
    _token_queue = None
    _stream_done = False
    _area = None
    response_text_index = None

    def execute(self, context):
        scene = context.scene
        chat_props = scene.blinnai_chat_props
        message = chat_props.input_text.strip()

        if not message:
            self.report({"WARNING"}, "Please enter a message.")
            return {"CANCELLED"}

        # Add user message
        user_msg = scene.blinnai_messages.add()
        user_msg.text = message
        user_msg.is_user = True

        # Clear input
        chat_props.input_text = ""

        # Get API key
        prefs = context.preferences.addons[__package__].preferences
        if not prefs.api_key:
            self.report({"ERROR"}, "No API key found. Please sign in.")
            return {"CANCELLED"}
        
        chat_props.is_ai_pending = True

        # Initialize response text (Add ai response)
        scene.blinnai_messages.add()
        self.response_text_index = len(scene.blinnai_messages) - 1

        self._token_queue = queue.Queue()
        self._stream_done = False
        self._area = context.area

        # Payload for POST
        #scene_context = get_sc
        payload = {"content": message}

        async def fetch_stream():
            try:
                with requests.Session() as session:
                    with session.post("http://localhost:8888/api/v1/conversation", json=payload, stream=True) as resp:
                        if resp.status_code == 200:
                            for chunk in resp.iter_content(chunk_size=1024):
                                if chunk:
                                    if self.response_text_index is not None:
                                        buffer = chunk.decode('utf-8', errors='replace')
                                        segments=buffer.split('\u001F')
                                        for json_str in segments:
                                            if json_str.strip():
                                                try:
                                                    data=json.loads(json_str.strip())
                                                    if isinstance(data, dict) and 'status' in data and 'token' in data:
                                                        self._token_queue.put(data)
                                                except json.JSONDecodeError:
                                                    continue
                        else:
                            self._token_queue.put({'status': 'error', 'token': f"Error: HTTP {resp.status_code}\n"})
            except Exception as e:
                self._token_queue.put({'status': 'error', 'token': f"Exception: {str(e)}\n"})
            finally:
                self._token_queue.put({'status': 'done', 'token': None})
        
        def run_async_fetch():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(fetch_stream())
            self._loop.close()
        
        thread = threading.Thread(target=run_async_fetch, daemon=True)
        thread.start()
        
        self._timer = context.window_manager.event_timer_add(0.1, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'TIMER':
            scene = context.scene
            chat_props = scene.blinnai_chat_props
            updated = False

            while not self._token_queue.empty():
                data = self._token_queue.get()
                status = data['status']

                if status == 'error' and self.response_text_index is not None:
                    scene.blinnai_messages[self.response_text_index].text += data['token']
                    updated = True
                elif status == 'done':
                    self._stream_done = True
                elif self.response_text_index is not None:
                    token = data['token']
                    if status == "Planning":
                        scene.blinnai_messages[self.response_text_index].text += token
                        updated = True
                    elif status == "Answering":
                        scene.blinnai_messages[self.response_text_index].text += token
                        updated = True
                    elif status == "Generating":
                        scene.blinnai_messages[self.response_text_index].script += token

            # Redraw UI if tokens were added
            if updated and self._area:
                self._area.tag_redraw()
            
            # Check if stream is done
            if self._stream_done and self._token_queue.empty():
                chat_props.is_ai_pending = False
                if self._timer:
                    context.window_manager.event_timer_remove(self._timer)
                    self._timer = None
                if self.response_text_index is not None and len(scene.blinnai_messages[self.response_text_index].script) > 0:
                    bpy.ops.blinnai.execute_script()
                return {'FINISHED'}

        return {'PASS_THROUGH'}

    def cancel(self, context):
        context.scene.blinnai_chat_props.is_ai_pending = False
        context.scene.blinnai_chat_props.is_executing_script = False
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None


def draw_chat_ui(layout, context):
    """Draw the chat UI with message bubbles and input bar."""
    scene = context.scene
    chat_props = scene.blinnai_chat_props
    prefs = context.preferences.addons[__package__].preferences
   
    # Project name
    project_name = (
        "Untitled"
        if not bpy.data.filepath
        else os.path.splitext(os.path.basename(bpy.data.filepath))[0]
    )
    row = layout.row(align=True)
    row.alignment = "CENTER"
    row.label(text=f"Project {project_name}")

    # Chat area (scrollable-like)
    box = layout.box()

    if not prefs.api_key:
        box.label(text="Please sign in to use the chat.", icon="ERROR")
        return

    # Message display
    for msg in scene.blinnai_messages:
        col = box.column(align=True)
        col.alignment = 'RIGHT' if msg.is_user else 'LEFT'

        display_text = f"You: {msg.text}" if msg.is_user else (f"Blinn: {msg.text}" if not msg.is_status else msg.text)

        lines = display_text.split('\n')

        max_width = 80

        for line in lines:
            wrapped_lines = textwrap.wrap(line, width=max_width, break_long_words=True)
            if not wrapped_lines:
                wrapped_lines = [line]
            for wrapped_line in wrapped_lines:
                col.label(text=wrapped_line)
        
        if len(msg.script):
            box = layout.box()
            col = box.column(align=True)
            col.alignment = 'CENTER'
            # handle executing too

    # Input bar and send button
    row = layout.row(align=True)
    row.enabled = not (chat_props.is_ai_pending or chat_props.is_executing_script)
    row.prop(scene.blinnai_chat_props, "input_text", text="", emboss=True)
    row.operator("blinnai.send_message", text="", icon="PLAY", emboss=True)


class BLINN_CHAT_OT_load_conversation(Operator):
    bl_idname = "blinnai.load_conversation"
    bl_label = "Load Conversation"
    bl_description = "Load previous conversation from API"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        if not hasattr(context, "scene") or not context.scene:
            bk_logger.debug("No valid scene context, skipping conversation load")
            self.report({"ERROR"}, "No valid scene context")
            return {"CANCELLED"}

        scene = context.scene
        chat_props = scene.blinnai_chat_props
        prefs = context.preferences.addons[__package__].preferences

        if not prefs.api_key:
            bk_logger.debug("No API key found, skipping conversation load")
            chat_props.is_loading_conversation = False
            self.report({"ERROR"}, "No API key found, please sign in")
            return {"CANCELLED"}

        chat_props.is_loading_conversation = True
        context.area.tag_redraw()

        try:
            headers = {"Authorization": f"Bearer {prefs.api_key}"}
            self.response = requests.get(
                "http://localhost:8888/api/v1/conversation", headers=headers
            )
            self.response.raise_for_status()
            self.queue = queue.Queue()
            self.running = True

            self.thread = threading.Thread(target=self.response_processor, daemon=True)
            self.thread.start()

            context.window_manager.modal_handler_add(self)
            self._timer = context.window_manager.event_timer_add(
                0.05, window=context.window
            )
            bk_logger.debug("Started conversation load timer")
            return {"RUNNING_MODAL"}

        except requests.RequestException as e:
            self.report({"ERROR"}, f"Failed to load conversation: {str(e)}")
            chat_props.is_loading_conversation = False
            chat_props.has_loaded_conversation = True
            context.area.tag_redraw()
            return {"CANCELLED"}

    def response_processor(self):
        try:
            bk_logger.debug("Processing API response")
            conversations = self.response.json()
            # Sort conversations by createdAt in descending order
            conversations.sort(
                key=lambda x: datetime.fromisoformat(
                    x.get("createdAt").replace("Z", "+00:00")
                ),
                reverse=True,
            )
            bk_logger.debug(
                f"Queued {len(conversations)} conversations: {conversations}"
            )
            self.queue.put(conversations)
        except (requests.RequestException, json.JSONDecodeError, ValueError) as e:
            self.queue.put({"error": str(e)})
            bk_logger.error(f"Response processing error: {str(e)}")
        finally:
            self.queue.put(None)  # Signal end of processing

    def modal(self, context, event):
        if event.type == "TIMER" and self.running:
            scene = context.scene
            chat_props = scene.blinnai_chat_props

            try:
                # Check queue for data
                while not self.queue.empty():
                    data = self.queue.get_nowait()
                    bk_logger.debug("Processing queue item")
                    if data is None:
                        # Processing ended
                        chat_props.is_loading_conversation = False
                        chat_props.has_loaded_conversation = True
                        self.cleanup(context)
                        try:
                            context.area.tag_redraw()
                        except AttributeError:
                            pass
                        bk_logger.debug("Conversation load complete")
                        return {"FINISHED"}

                    if isinstance(data, dict) and "error" in data:
                        self.report(
                            {"ERROR"}, f"Failed to load conversation: {data['error']}"
                        )
                        bk_logger.error(f"Conversation load error: {data['error']}")
                        chat_props.is_loading_conversation = False
                        chat_props.has_loaded_conversation = True
                        self.cleanup(context)
                        try:
                            context.area.tag_redraw()
                        except AttributeError:
                            pass
                        return {"FINISHED"}

                    # Process conversations
                    bk_logger.debug(f"Processing {len(data)} conversation items")
                    while len(scene.blinnai_messages) > 0:
                        scene.blinnai_messages.remove(0)
                        bk_logger.debug("Cleared existing message")
                    for conv in data:
                        if conv.get("role") == "user":
                            msg = scene.blinnai_messages.add()
                            msg.text = conv.get("content", "")
                            msg.is_user = True
                            bk_logger.debug(f"Added user message from API: {msg.text}")
                        elif conv.get("explaination"):
                            msg = scene.blinnai_messages.add()
                            msg.text = conv.get("explaination", "")
                            msg.is_user = False
                            bk_logger.debug(f"Added AI explanation from API: {msg.text}")
                    chat_props.is_loading_conversation = False
                    chat_props.has_loaded_conversation = True
                    self.cleanup(context)
                    try:
                        context.area.tag_redraw()
                    except AttributeError:
                        pass
                    bk_logger.debug("Conversation load complete, messages added")
                    return {"FINISHED"}
            except Exception as e:
                self.report({"ERROR"}, f"Conversation load error: {str(e)}")
                bk_logger.error(f"Conversation load error: {str(e)}")
                chat_props.is_loading_conversation = False
                chat_props.has_loaded_conversation = True
                self.cleanup(context)
                try:
                    context.area.tag_redraw()
                except AttributeError:
                    pass
                return {"FINISHED"}

        return {"RUNNING_MODAL"}

    def cleanup(self, context):
        if hasattr(self, "response"):
            self.response.close()
        if hasattr(self, "_timer"):
            context.window_manager.event_timer_remove(self._timer)
        self.running = False


classes = (
    BLINN_CHAT_OT_execute_script,
    BLINN_CHAT_OT_send_message,
    BLINN_CHAT_OT_load_conversation,
)

## User can link the ai to various assets or other addons
