bl_info = {
    "name": "Blinn AI: Automate Blender with AI",
    "author": "Soumya Ranjan Sahu",
    "maintainer": "Soumya Ranjan Sahu",
    "version": (0, 1, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > BlinnAI",
    "description": "BlinnAI Add-on with Google OAuth login",
    "category": "3D View",
    "website": "http://localhost:3005",
}

import bpy
from bpy.types import Operator, Panel, AddonPreferences, PropertyGroup
from bpy.props import StringProperty, BoolProperty, CollectionProperty, PointerProperty
from .auth import login, logout
from . import ui_panels


class BlinnAIChatProperties(PropertyGroup):
    """Properties for chat input."""
    input_text: StringProperty(
        name="Chat Input",
        description="Enter your message here",
        default=""
    )
    is_loading_conversation: BoolProperty(
        name="Loading Conversation",
        description="Indicates if conversation is being loaded from API",
        default=False
    )
    has_loaded_conversation: BoolProperty(
        name="Has Loaded Conversation",
        description="Indicates if conversation has been loaded for this session",
        default=False
    )

class ChatMessage(PropertyGroup):
    """Represents a single chat message."""
    text: StringProperty(name="Text", default="")
    is_user: BoolProperty(name="Is User", default=False)
    is_status: BoolProperty(name="Is Status", default=False)

class BlinnAI_Preferences(AddonPreferences):
    bl_idname = __name__

    api_key: StringProperty(
        name="API Key",
        description="BlinnAI API Key (non-expiring)",
        default="",
        subtype="PASSWORD",
    )

    login_attempt: BoolProperty(
        name="Login Attempt", description="Track ongoing login attempt", default=False
    )

    keep_preferences: BoolProperty(
        name="Keep Preferences",
        description="Retain add-on preferences after disabling",
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        layout.label(text="BlinnAI Add-on Settings")

        # Signin Button
        if self.api_key.strip() == "":
            layout.operator("blinnai.manual_signin", text="Sign In", icon="URL")
            layout.label(
                text="Sign up to access BlinnAI features. Get started with a free account!"
            )
        else:
            layout.operator("blinnai.signout", text="Sign Out", icon="URL")

        layout.prop(self, "api_key", text="Your API Key", emboss=True)
        if self.api_key:
            layout.operator("blinnai.clear_key", text="Clear", icon="X")

        layout.prop(self, "keep_preferences")


class BLINN_SIGNIN_OT_manual_signin(Operator):
    bl_idname = "blinnai.manual_signin"
    bl_label = "Sign In"
    bl_description = "Open browser for authentication"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from .auth import login

        login(signup=False)  # Open login page
        self.report(
            {"INFO"},
            "Browser opened for sign-in. Complete authentication and return here.",
        )
        return {"FINISHED"}


class BLINN_SIGNOUT_OT_signout(Operator):
    bl_idname = "blinnai.signout"
    bl_label = "Sign Out"
    bl_description = "Sign out and clear API key"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from .auth import logout

        logout()
        self.report({"INFO"}, "Signed out successfully.")
        return {"FINISHED"}


class BLINN_CLEAR_OT_clear_key(Operator):
    bl_idname = "blinnai.clear_key"
    bl_label = "Clear Key"
    bl_description = "Clear the API key"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        context.preferences.addons[__package__].preferences.api_key = ""
        self.report({"INFO"}, "API key cleared.")
        return {"FINISHED"}


class BLINN_PT_main_panel(Panel):
    bl_label = "Blinn AI Login"
    bl_idname = "BLINN_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BlinnAI"

    def draw(self, context):
        layout = self.layout
        prefs = context.preferences.addons[__package__].preferences

        if not prefs.api_key:
            layout.label(text="Not logged in")
            layout.operator("wm.blinnai_login", text="Login/Signup")
            if prefs.login_attempt:
                layout.operator("wm.blinnai_login_cancel", text="Cancel Login")
        else:
            layout.label(text="Logged in")
            layout.label(text=f"Key: {prefs.api_key[:10]}...")
            layout.operator("wm.blinnai_logout", text="Logout")

        layout.separator()
        ui_panels.draw_chat_ui(layout, context)


classes = ()


def register():
    from .auth import classes as oauth_classes
    from .ui_panels import classes as ui_classes
    global classes

    classes = (
        oauth_classes
        + ui_classes
        + (
            BlinnAI_Preferences,
            BLINN_SIGNIN_OT_manual_signin,
            BLINN_SIGNOUT_OT_signout,
            BLINN_CLEAR_OT_clear_key,
            BLINN_PT_main_panel,
            ChatMessage,
            BlinnAIChatProperties
        )
    )
    for cls in classes:
        bpy.utils.register_class(cls)
    
    bpy.types.Scene.blinnai_messages = CollectionProperty(type=ChatMessage)
    bpy.types.Scene.blinnai_chat_props = PointerProperty(
        type=BlinnAIChatProperties,
        name="BlinnAI Chat Properties",
        description="Properties for chat input"
    )
    #bpy.ops.blinnai.load_conversation()
    #bpy.app.timers.register(lambda: delayed_load_conversation(bpy.context), first_interval=1.0)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.blinnai_messages
    del bpy.types.Scene.blinnai_chat_props


if __name__ == "__main__":
    register()
