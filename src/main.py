import sys
import signal
import asyncio
import gi
import os
import traceback

from gettext import gettext as _

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.events import GLibEventLoopPolicy
asyncio.set_event_loop_policy(GLibEventLoopPolicy())

from gi.repository import Gtk, Gio, Adw, GObject, GLib
from .widgets import KaghezWindow, build_shortcuts
from .widgets.preferences import KaghezPreferences
from .widgets.setup import SetupWindow

from .integrations import Suwayomi

if sys.platform == "win32":
    from . import winproc

LOCAL_SERVER_URL = "http://localhost:4567"
SERVER_READY_TIMEOUT = 10
SERVER_POLL_INTERVAL = 0.5
# Cold starts are much slower on Windows: Defender scans the ~180 MB jar
# and the bundled JRE the first time they run.
LOCAL_SERVER_READY_TIMEOUT = 60 if sys.platform == "win32" else SERVER_READY_TIMEOUT
SERVER_JAR = 'Suwayomi-Server-v2.3.2361.jar'


def get_pkgdatadir() -> str:
    if getattr(sys, 'frozen', False):
        # PyInstaller keeps our modules inside its archive, so __file__
        # doesn't point into the installed tree. The data lives where
        # kaghez.in's frozen branch puts pkgdatadir.
        return os.path.join(sys._MEIPASS, 'share', 'kaghez')
    moduledir = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(moduledir)


class KaghezApplication(Adw.Application):
    """The main application singleton class."""

    def __init__(self):
        flags = Gio.ApplicationFlags.DEFAULT_FLAGS
        if sys.platform == "win32":
            # Single-instance mode goes through D-Bus, which Windows
            # doesn't have without shipping and autolaunching gdbus.exe.
            flags |= Gio.ApplicationFlags.NON_UNIQUE
        super().__init__(application_id='com.rini.kaghez',
                         flags=flags,
                         resource_base_path='/com/rini/kaghez')
        self.settings = Gio.Settings(schema_id="com.rini.kaghez")
        self.suwayomi = Suwayomi()

        self.server_proc: Gio.Subprocess | None = None
        self.server_output_task: asyncio.Task | None = None

        self.create_action('quit', lambda *_: self.quit(), ['<control>q'])
        self.create_action('preferences', self.on_preferences_action, ['<control>comma'])
        self.create_action('shortcuts', self.on_shortcuts_action, ['<control>question', '<control>slash'])
        self.create_action('about', self.on_about_action)
        self.create_action('change-instance', self.on_change_instance_action)

    def do_activate(self):
        """Called when the application is activated."""
        win = self.props.active_window
        if win:
            win.present()
            return

        mode = self.settings.get_string('suwayomi-mode')
        if mode in ("local", "remote"):
            # Returning user: try the saved config with nothing visible.
            # hold() keeps GApplication alive while no window exists yet.
            self.hold()
            task = asyncio.create_task(self.launch_or_setup(mode, self.settings.get_string('suwayomi-url')))
            task.add_done_callback(self.log_task_exception)
        else:
            self.show_setup_window()

    @staticmethod
    def log_task_exception(task: asyncio.Task):
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            print("launch_or_setup crashed:", flush=True)
            traceback.print_exception(type(exc), exc, exc.__traceback__)

    async def launch_or_setup(self, mode: str, url: str):
        try:
            if not await self.launch(mode, url):
                self.show_setup_window(error=_("Couldn't reconnect. Check your setup and try again."))
        finally:
            self.release()

    async def launch(self, mode: str, url: str) -> bool:
        """Get a server running (local or remote) and wait until it
        actually answers before doing anything else. Returns whether it
        succeeded; presents the main window itself on success."""
        if mode == "local":
            if not await self.start_local_server():
                return False
            server_url = LOCAL_SERVER_URL
        else:
            if not url:
                return False
            server_url = url

        self.suwayomi.reconnect(server_url)

        timeout = LOCAL_SERVER_READY_TIMEOUT if mode == "local" else SERVER_READY_TIMEOUT
        if not await self.wait_for_server_ready(timeout):
            if mode == "local":
                self.stop_local_server()
            return False

        self.settings.set_string('suwayomi-mode', mode)
        self.settings.set_string('suwayomi-url', url if mode == "remote" else "")

        KaghezWindow(application=self).present()
        return True

    def find_bundled_jar(self) -> str | None:
        jar_path = os.path.join(get_pkgdatadir(), SERVER_JAR)
        return jar_path if os.path.isfile(jar_path) else None

    def find_java(self) -> str:
        """Prefer a JRE shipped next to the jar (the Windows build bundles
        one); otherwise rely on `java` from PATH, like the Flatpak does."""
        java_name = "java.exe" if sys.platform == "win32" else "java"
        # Not named "jre": the server's class scanner (ClassGraph) treats the
        # parent of a "jre" folder as part of the JDK and skips the jar
        # sitting next to it, and the server then fails to start.
        bundled = os.path.join(get_pkgdatadir(), 'java', 'bin', java_name)
        return bundled if os.path.isfile(bundled) else "java"

    async def start_local_server(self) -> bool:
        if self.server_proc is not None:
            return True  # already running

        jar_path = self.find_bundled_jar()
        if jar_path is None:
            print("local Suwayomi server jar not found")
            return False

        argv = [
            self.find_java(),
            "-Dsuwayomi.tachidesk.config.server.systemTrayEnabled=false",
            "-Dsuwayomi.tachidesk.config.server.initialOpenInBrowserEnabled=false",
            "-Dsuwayomi.tachidesk.config.server.kcefEnabled=false",
            "-jar", jar_path,
        ]

        if sys.platform == "win32":
            try:
                self.server_proc = winproc.spawn_server(argv)
            except OSError as e:
                print(f"failed to start local server: {e}")
                self.server_proc = None
                return False
            return True

        launcher = Gio.SubprocessLauncher.new(
            Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE
        )
        try:
            self.server_proc = launcher.spawnv(argv)
        except GLib.Error as e:
            print(f"failed to start local server: {e.message}")
            self.server_proc = None
            return False

        self.server_output_task = asyncio.create_task(self.pump_server_output())
        return True

    async def pump_server_output(self):
        """Drain the server's stdout/stderr so crashes/logs are visible
        instead of silently filling an unread pipe."""
        if self.server_proc is None:
            return
        stdout = self.server_proc.get_stdout_pipe()
        stream = Gio.DataInputStream.new(stdout)
        try:
            while True:
                line, _len = await stream.read_line_async(GLib.PRIORITY_DEFAULT)
                if line is None:
                    break
                print(f"[suwayomi] {line.decode('utf-8', errors='replace')}", flush=True)
        except GLib.Error as e:
            print(f"[suwayomi] output stream error: {e.message}", flush=True)

    def stop_local_server(self):
        if self.server_proc is None:
            return
        if sys.platform == "win32":
            winproc.stop_server(self.server_proc)
        elif self.server_proc.get_identifier():
            self.server_proc.send_signal(signal.SIGTERM)
            try:
                self.server_proc.wait(None)
            except GLib.Error:
                self.server_proc.force_exit()
        self.server_proc = None
        if self.server_output_task is not None:
            self.server_output_task.cancel()
            self.server_output_task = None

    async def wait_for_server_ready(self, timeout: float = SERVER_READY_TIMEOUT) -> bool:
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            self.suwayomi.session = None  # force a fresh handshake attempt
            settings = await self.suwayomi.getServerSettings()
            if settings:
                return True
            await asyncio.sleep(SERVER_POLL_INTERVAL)
        return False

    def show_setup_window(self, error: str | None = None):
        window = SetupWindow(application=self, error=error)
        window.present()

    def on_change_instance_action(self, *args):
        win = self.props.active_window
        self.stop_local_server()
        if win:
            win.close()
        self.show_setup_window()

    def do_shutdown(self):
        """Called right before the application exits."""
        self.stop_local_server()
        self.suwayomi.cache.close()
        Adw.Application.do_shutdown(self)

    def on_about_action(self, *args):
        about = Adw.AboutDialog(application_name='Kaghez',
                                application_icon='com.rini.kaghez',
                                developer_name='Riyan Parvez',
                                version='0.8.8',
                                translator_credits = _('translator-credits'),
                                developers=['Riyan Parvez (rini)'],
                                copyright='© 2026 Riyan Parvez')
        about.present(self.props.active_window)

    def on_preferences_action(self, widget, _):
        preferences = KaghezPreferences()
        preferences.present(self.props.active_window)

    def on_shortcuts_action(self, widget, _):
        shortcuts = build_shortcuts()
        shortcuts.present(self.props.active_window)

    def create_action(self, name, callback, shortcuts=None, parameter_type=None):
        action = Gio.SimpleAction.new(name, parameter_type)
        action.connect("activate", callback)
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f"app.{name}", shortcuts)

def main(version):
    app = KaghezApplication()
    return app.run(sys.argv)
