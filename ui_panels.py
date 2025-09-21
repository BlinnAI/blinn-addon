import os
import bpy
from bpy.types import Operator
#from bpy.props import StringProperty, BoolProperty
import logging

bk_logger = logging.getLogger(__name__)

#class ChatMessage(PropertyGroup):
#    """Represents a single chat message."""
#    text: StringProperty(name="Text", default="")
#    is_user: BoolProperty(name="Is User", default=False)


#class BlinnAIChatProperties(PropertyGroup):
#    """Properties for chat input."""
#    input_text: StringProperty(
#        name="Chat Input",
#        description="Enter your message here",
#        default=""
#    )


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
        #bk_logger.debug(f"Added user message: {message}")

        # Add mock AI response (replace with API call later)
        ai_msg = scene.blinnai_messages.add()
        ai_msg.text = f"AI: Got your message: {message}"
        ai_msg.is_user = False
        #bk_logger.debug(f"Added AI response: {ai_msg.text}")

        # Clear input
        chat_props.input_text = ""

        return {"FINISHED"}


def draw_chat_ui(layout, context):
    """Draw the chat UI with message bubbles and input bar."""
    scene = context.scene
    chat_props = scene.blinnai_messages
    prefs = context.preferences.addons[__package__].preferences

    # Chat area (scrollable-like)
    project_name = "Untitled" if not bpy.data.filepath else os.path.splitext(os.path.basename(bpy.data.filepath))[0]
    box = layout.box()
    row = box.row(align=True)
    row.alignment = 'CENTER'
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
            row.label(text=f"Blinn: {msg.text}")

    # Input bar and send button
    row = layout.row(align=True)
    row.prop(scene.blinnai_chat_props, "input_text", text="", emboss=True)
    row.operator("blinnai.send_message", text="", icon="PLAY")


classes = (
    #ChatMessage,
    #BlinnAIChatProperties,
    BLINN_CHAT_OT_send_message,
)


#def register():
#    for cls in classes:
#        bpy.utils.register_class(cls)
#    bpy.types.Scene.blinnai_messages = CollectionProperty(type=ChatMessage)
#    bpy.types.Scene.blinnai_chat_props = PointerProperty(
#        type=BlinnAIChatProperties,
#        name="BlinnAI Chat Properties",
#        description="Properties for chat input",
#    )
#    #bpy.types.Scene.blinnai_chat_props.input_text = StringProperty(
#    #    name="Chat Input", description="Enter your message here", default=""
#    #)


#def unregister():
#    del bpy.types.Scene.blinnai_messages
#    del bpy.types.Scene.blinnai_chat_props
#    for cls in reversed(classes):
#        bpy.utils.unregister_class(cls)
