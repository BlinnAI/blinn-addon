import os
import bpy
from bpy.types import Operator
import json
import requests
import queue
import threading
import tempfile
import logging
from datetime import datetime

bk_logger = logging.getLogger(__name__)


class BLINN_CHAT_OT_send_message(Operator):
    bl_idname = "blinnai.send_message"
    bl_label = "Send Message"
    bl_description = "Send the chat message"
    bl_options = {"REGISTER", "UNDO"}

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

        # Initialize status message
        status_msg = scene.blinnai_messages.add()
        self.status_msg_index = len(scene.blinnai_messages) - 1

        # Send requets to stream response
        try:
            headers = {"Authorization": f"Bearer {prefs.api_key}"}
            self.response = requests.post(
                "http://localhost:8888/api/v1/conversation",
                json={
                    "content": message,
                },
                headers=headers,
                stream=True,
            )
            self.response.raise_for_status()
            self.queue = queue.Queue()
            self.temp_file_path = None
            self.running = True

            # Start background thread for stream processing
            self.thread = threading.Thread(target=self.stream_processor, daemon=True)
            self.thread.start()

            # Start timer for non-blocking processing
            context.window_manager.modal_handler_add(self)
            self._timer = context.window_manager.event_timer_add(
                0.05, window=context.window
            )
            context.area.tag_redraw()
            return {"RUNNING_MODAL"}

        except requests.RequestException as e:
            self.report({"ERROR"}, f"Failed to connect to API: {str(e)}")
            return {"CANCELLED"}

    def stream_processor(self):
        try:
            for line in self.response.iter_lines():
                if line and self.running:
                    decoded_line = line.decode("utf-8")
                    if decoded_line.startswith("data: "):
                        try:
                            data = json.loads(decoded_line[6:])
                            self.queue.put(data)
                        except json.JSONDecodeError as e:
                            self.queue.put(
                                {
                                    "status": "Error",
                                    "error": f"Invalid response format: {str(e)}",
                                }
                            )
            self.queue.put(None)  # Signal end of stream
        except requests.RequestException as e:
            self.queue.put({"status": "Error", "error": str(e)})
        except e:
            self.queue.put({"status": "Error", "error": str(e)})
        finally:
            self.queue.put(None)  # Signal end of stream

    def modal(self, context, event):
        if event.type == "TIMER" and self.running:
            scene = context.scene
            try:
                while not self.queue.empty():
                    data = self.queue.get_nowait()
                    if data is None:
                        if self.status_msg_index is not None:
                            scene.blinnai_messages.remove(self.status_msg_index)
                            self.status_msg_index = None

                        self.cleanup(context)
                        return {"FINISHED"}

                    if data.get("status") == "Error":
                        self.report(
                            {"ERROR"},
                            f"API Error: {data.get('error', 'Unknown error')}",
                        )
                        if self.status_msg_index is not None:
                            scene.blinnai_messages.remove(self.status_msg_index)
                            self.status_msg_index = None
                        self.cleanup(context)
                        return {"FINISHED"}
                    elif data.get("status") == "Complete":
                        if self.status_msg_index is not None:
                            scene.blinnai_messages.remove(self.status_msg_index)
                            self.status_msg_index = None
                        script = data.get("script")
                        if script:
                            try:
                                with tempfile.NamedTemporaryFile(
                                    mode="w", suffix=".py", delete=False
                                ) as temp_file:
                                    temp_file.write(script)
                                    self.temp_file_path = temp_file.name
                                bpy.ops.script.python_file_run(
                                    filepath=self.temp_file_path
                                )
                            except Exception as e:
                                self.report(
                                    {"ERROR"}, f"Script execution failed: {str(e)}"
                                )
                        explanation = data.get("explaination")
                        if explanation:
                            ai_msg = scene.blinnai_messages.add()
                            ai_msg.text = explanation
                            ai_msg.is_user = False
                        # projectId = data.get("projectId")
                        # if projectId:
                        #    # save project Id unless until user is working on current project in blender or loads the same project file

                        self.cleanup(context)
                        context.area.tag_redraw()
                        return {"FINISHED"}
                    else:
                        if self.status_msg_index is not None:
                            scene.blinnai_messages[self.status_msg_index].text = (
                                data.get("status", "")
                            )
                            context.area.tag_redraw()

            except Exception as e:
                self.report({"ERROR"}, f"Stream error: {str(e)}")
                if self.status_msg_index is not None:
                    scene.blinnai_messages.remove(self.status_msg_index)
                    self.status_msg_index = None
                self.cleanup(context)
                return {"FINISHED"}

            return {"RUNNING_MODAL"}

        return {"RUNNING_MODAL"}

    def cleanup(self, context):
        if hasattr(self, "response"):
            self.response.close()
        if self.temp_file_path and os.path.exists(self.temp_file_path):
            os.unlink(self.temp_file_path)
        if hasattr(self, "_timer"):
            context.window_manager.event_timer_remove(self._timer)
        self.running = False


def draw_chat_ui(layout, context):
    """Draw the chat UI with message bubbles and input bar."""
    scene = context.scene
    chat_props = scene.blinnai_messages
    prefs = context.preferences.addons[__package__].preferences

    # Chat area (scrollable-like)
    box = layout.box()

    # Load previous chats button
    row = box.row(align=True)
    row.alignment = "CENTER"
    row.enabled = not scene.blinnai_chat_props.is_loading_conversation
    row.operator("blinnai.load_conversation", text="Load previous chats")

    # Project name
    project_name = (
        "Untitled"
        if not bpy.data.filepath
        else os.path.splitext(os.path.basename(bpy.data.filepath))[0]
    )
    row = box.row(align=True)
    row.alignment = "CENTER"
    row.label(text=f"Project {project_name}")

    if not prefs.api_key:
        box.label(text="Please sign in to use the chat.", icon="ERROR")
        return

    # Message display
    for msg in scene.blinnai_messages:
        row = box.row(align=True)
        if msg.is_user:
            row.alignment = "RIGHT"
            row.label(text=f"You: {msg.text}")
        else:
            row.alignment = "LEFT"
            row.label(text=f"Blinn: {msg.text}" if not msg.is_status else msg.text)

    # Input bar and send button
    row = layout.row(align=True)
    row.enabled = (
        not scene.blinnai_chat_props.is_loading_conversation
    )  # Fixed: Use row.enabled
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
    BLINN_CHAT_OT_load_conversation,
    BLINN_CHAT_OT_send_message,
)
