# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if you have not received it, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

import logging
from urllib.parse import quote as urlquote
from webbrowser import open_new_tab

import bpy
from bpy.props import BoolProperty, StringProperty

from . import client, global_vars

bk_logger = logging.getLogger(__name__)


def clean_login_data():
    preferences = bpy.context.preferences.addons[__package__].preferences
    preferences.login_attempt = False
    preferences.api_key = ""


def logout() -> None:
    """Logs out user from add-on. Clears the API key."""
    bk_logger.info("Logging out.")
    clean_login_data()
    client.stop_server()


def login(signup: bool) -> None:
    """Logs user into the addon.
    Opens a browser with login page. Once user is logged it redirects browser to localhost callback handling api_key via URL query parameter.
    """
    port = client.get_port()
    bk_logger.debug(f"Port: {port}, type: {type(port)}")
    callback_url = f"http://localhost:{port}/callback"
    bk_logger.debug(f"Callback URL: {callback_url}, type: {type(callback_url)}")
    login_base = f"{global_vars.SERVER}"
    bk_logger.debug(f"login_base: {login_base}, type: {type(login_base)}")
    #if signup:
    #    next_url = urlquote(f"{login_base}?callback={urlquote(callback_url)}")
    #    authorize_url = f"{global_vars.SERVER}/register?next={next_url}"
    #else:
    authorize_url = f"{login_base}?callback={urlquote(callback_url)}"
    bk_logger.debug(f"Authorize URL: {authorize_url}, type: {type(authorize_url)}")
    ok = open_new_tab(authorize_url)
    bk_logger.info(f"Login page in browser opened ({ok})")
    preferences = bpy.context.preferences.addons[__package__].preferences
    preferences.login_attempt = True
    client.start_server(callback_url)


def write_tokens(auth_token, _refresh_token=None, _oauth_response=None):
    """Simplified token writer for non-expiring API key."""
    preferences = bpy.context.preferences.addons[__package__].preferences
    preferences.login_attempt = False
    preferences.api_key = auth_token


class LoginOnline(bpy.types.Operator):
    """Login or register online on BlinnAI webpage"""

    bl_idname = "wm.blinnai_login"
    bl_label = "BlinnAI login/signup"
    bl_options = {"REGISTER", "UNDO"}

    signup: BoolProperty(
        name="create a new account",
        description="True for register, otherwise login",
        default=False,
        options={"SKIP_SAVE"},
    )

    message: StringProperty(
        name="Message",
        description="",
        default="Clicking OK takes you to web login.",
    )

    @classmethod
    def poll(cls, context):
        return True

    def draw(self, context):
        layout = self.layout
        for line in self.message.split("\n"):
            layout.label(text=line)

    def execute(self, context):
        preferences = bpy.context.preferences.addons[__package__].preferences
        preferences.login_attempt = True
        login(self.signup)
        return {"FINISHED"}

    def invoke(self, context, event):
        wm = bpy.context.window_manager
        preferences = bpy.context.preferences.addons[__package__].preferences
        preferences.api_key = ""
        return wm.invoke_props_dialog(self)


class Logout(bpy.types.Operator):
    """Logout from BlinnAI immediately"""

    bl_idname = "wm.blinnai_logout"
    bl_label = "BlinnAI logout"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        logout()
        return {"FINISHED"}


class CancelLoginOnline(bpy.types.Operator):
    """Cancel login attempt"""

    bl_idname = "wm.blinnai_login_cancel"
    bl_label = "BlinnAI login cancel"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        preferences = bpy.context.preferences.addons[__package__].preferences
        preferences.login_attempt = False
        client.stop_server()
        return {"FINISHED"}


classes = (
    LoginOnline,
    CancelLoginOnline,
    Logout,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in classes:
        bpy.utils.unregister_class(c)
