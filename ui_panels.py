import os
import bpy
from bpy.types import Operator
import json
import requests
import uuid
import queue
import threading
import tempfile
import logging

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
        status_msg.text = "Starting..."
        status_msg.is_user = False
        status_msg.is_status = True
        self.status_msg_index = len(scene.blinnai_messages) - 1

        # Send requets to stream response
        try:
            headers = {"Authorization": f"Bearer {prefs.api_key}"}
            self.response = requests.post(
                "http://localhost:8888/api/v1/conversation",
                json={
                    "projectId": None,
                    "conversation": [
                        {
                            "messageId": str(uuid.uuid4()),
                            "role": "user",
                            "content": message,
                            "sceneContext": {},
                        }
                    ],
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
                    decoded_line = line.decode('utf-8')
                    if decoded_line.startswith("data: "):
                        try:
                            data = json.loads(decoded_line[6:])
                            self.queue.put(data)
                        except json.JSONDecodeError as e:
                            self.queue.put({"status": "Error", "error": f"Invalid response format: {str(e)}"})
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
                        return {'FINISHED'}
                    
                    if data.get("status") == "Error":
                        self.report({'ERROR'}, f"API Error: {data.get('error', 'Unknown error')}")
                        if self.status_msg_index is not None:
                            scene.blinnai_messages.remove(self.status_msg_index)
                            self.status_msg_index = None
                        self.cleanup(context)
                        return {'FINISHED'}
                    elif data.get("status") == "Complete":
                        if self.status_msg_index is not None:
                            scene.blinnai_messages.remove(self.status_msg_index)
                            self.status_msg_index = None
                        script = data.get("script")
                        if script:
                            try:
                                with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as temp_file:
                                    temp_file.write(script)
                                    self.temp_file_path = temp_file.name
                                bpy.ops.script.python_file_run(filepath=self.temp_file_path)
                            except Exception as e:
                                self.report({'ERROR'}, f"Script execution failed: {str(e)}")
                        explanation = data.get("explaination")
                        if explanation:
                            ai_msg = scene.blinnai_messages.add()
                            ai_msg.text = explanation
                            ai_msg.is_user = False
                        self.cleanup(context)
                        context.area.tag_redraw()
                        return {'FINISHED'}
                    else:
                        if self.status_msg_index is not None:
                            scene.blinnai_messages[self.status_msg_index].text = data.get("status", "")
                            context.area.tag_redraw()
            
            except Exception as e:
                self.report({'ERROR'}, f"Stream error: {str(e)}")
                if self.status_msg_index is not None:
                    scene.blinnai_messages.remove(self.status_msg_index)
                    self.status_msg_index = None
                self.cleanup(context)
                return {'FINISHED'}

            return {"RUNNING_MODAL"}

        return {'RUNNING_MODAL'}

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
    project_name = (
        "Untitled"
        if not bpy.data.filepath
        else os.path.splitext(os.path.basename(bpy.data.filepath))[0]
    )
    box = layout.box()
    row = box.row(align=True)
    row.alignment = "CENTER"
    row.label(text=f"Project {project_name}")

    if not prefs.api_key:
        box.label(text="Please sign in to use the chat.", icon="ERROR")
        return

    # Message display
    for msg in chat_props:
        row = box.row(align=True)
        if msg.is_user:
            row.alignment = "RIGHT"
            row.label(text=f"You: {msg.text}")
        else:
            row.alignment = "LEFT"
            row.label(text=f"Blinn: {msg.text}" if not msg.is_status else msg.text)

    # Input bar and send button
    row = layout.row(align=True)
    row.prop(scene.blinnai_chat_props, "input_text", text="", emboss=True)
    row.operator("blinnai.send_message", text="", icon="PLAY")


classes = (
    BLINN_CHAT_OT_send_message,
)

