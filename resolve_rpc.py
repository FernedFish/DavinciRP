import logging
import os
import sys
import time

import psutil
from pypresence import Presence


CLIENT_ID = "1565356399775580230"
UPDATE_INTERVAL_SECONDS = 15

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def configure_resolve_paths():
    """Configure the Resolve scripting library and modules path."""
    if sys.platform.startswith("win"):
        default_library = r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"
        default_modules = r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules"
    elif sys.platform == "darwin":
        default_library = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
        default_modules = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules"
    else:
        default_library = "/opt/resolve/libs/Fusion/fusionscript.so"
        default_modules = "/opt/resolve/Developer/Scripting/Modules"

    library = os.environ.get("RESOLVE_SCRIPT_LIB", default_library)
    modules = os.environ.get("RESOLVE_SCRIPT_MODULES", default_modules)
    os.environ["RESOLVE_SCRIPT_LIB"] = library

    if modules not in sys.path:
        sys.path.append(modules)


configure_resolve_paths()

try:
    import DavinciResolveScript as dvr_script
except ImportError as error:
    logger.warning("DaVinci Resolve scripting modules are unavailable: %s", error)
    dvr_script = None

def get_resolve_activity():
    """Return the current project name and Resolve page, if available."""
    if dvr_script is None:
        return "No Project Open", "Editing"

    try:
        resolve = dvr_script.scriptapp("Resolve")
        if not resolve:
            return "No Project Open", "Editing"

        project_name = "No Project Open"
        project_manager = resolve.GetProjectManager()
        if project_manager:
            current_project = project_manager.GetCurrentProject()
            if current_project:
                project_name = current_project.GetName() or "No Project Open"

        page = resolve.GetCurrentPage()
        if not isinstance(page, str) or not page:
            page = "Editing"

        return project_name, page
    except Exception as error:
        logger.debug("Unable to retrieve DaVinci Resolve state: %s", error)
        return "No Project Open", "Editing"


def is_resolve_running():
    """Return whether a DaVinci Resolve process is active."""
    if sys.platform.startswith("win"):
        process_name = "resolve.exe"
    else:
        process_name = "resolve"

    try:
        for proc in psutil.process_iter(["name"]):
            name = proc.info.get("name")
            if name and name.lower() == process_name:
                return True
    except psutil.Error as error:
        logger.debug("Unable to inspect process list: %s", error)
    return False

class DaVinciPresence:
    def __init__(self):
        self.rpc = Presence(CLIENT_ID)
        self.connected = False
        self.resolve_was_running = False
        self.session_start = None
        self.last_payload = None

    def connect(self):
        if self.connected:
            return True

        try:
            self.rpc.connect()
            self.connected = True
            logger.info("Connected to Discord.")
            return True
        except Exception as error:
            logger.warning("Discord is unavailable; will retry: %s", error)
            return False

    def disconnect(self, reason=""):
        if not self.connected:
            return

        try:
            self.rpc.close()
        except Exception as error:
            logger.debug("Error while closing Discord RPC: %s", error)
        finally:
            self.connected = False
            logger.info("Disconnected from Discord.%s", f" {reason}" if reason else "")

    def update(self):
        resolve_running = is_resolve_running()

        if not resolve_running:
            if self.resolve_was_running:
                self.disconnect("DaVinci Resolve closed.")
            self.resolve_was_running = False
            self.session_start = None
            self.last_payload = None
            return

        if not self.resolve_was_running:
            self.session_start = int(time.time())
            self.last_payload = None

        self.resolve_was_running = True

        if not self.connect():
            return

        project_name, page = get_resolve_activity()
        payload = {
            "details": f"Project: {project_name}",
            "state": f"{page} workspace",
            "large_image": "resolve_logo",
            "large_text": "DaVinci Resolve Studio",
            "start": self.session_start,
        }

        if payload == self.last_payload:
            return

        try:
            self.rpc.update(**payload)
            self.last_payload = payload
        except Exception as error:
            logger.error("Discord presence update failed: %s", error)
            self.disconnect("Presence connection reset.")

    def close(self):
        self.disconnect("Application stopped.")


def main():
    logger.info("Starting DaVinci Resolve Discord Rich Presence.")
    presence = DaVinciPresence()

    try:
        while True:
            presence.update()
            time.sleep(UPDATE_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        logger.info("Stopping Rich Presence.")
    finally:
        presence.close()


if __name__ == "__main__":
    main()