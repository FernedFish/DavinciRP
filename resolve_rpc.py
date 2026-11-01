import logging
import os
import sys
import time
import importlib
from pathlib import Path

import psutil
from pypresence import Presence


CLIENT_ID = "1565356399775580230"
UPDATE_INTERVAL_SECONDS = 15
SCRIPT_RETRY_SECONDS = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def first_existing_file(candidates):
    """Return the first existing file from an ordered list of paths."""
    for candidate in candidates:
        if candidate:
            path = Path(candidate).expanduser()
            if path.is_file():
                return path.resolve()
    return None


def running_resolve_executables():
    """Find installed Resolve executable paths without assuming one install location."""
    executables = []
    try:
        for proc in psutil.process_iter(["exe", "name"]):
            try:
                name = (proc.info.get("name") or "").lower()
                executable = proc.info.get("exe")
                if executable and (
                    name.startswith("resolve")
                    or Path(executable).name.lower() == "resolve.exe"
                ):
                    executables.append(Path(executable))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except psutil.Error:
        pass
    return executables


def discover_resolve_paths():
    """Discover the Resolve library and Python scripting modules paths."""
    running_executables = running_resolve_executables()
    candidates = []

    if sys.platform.startswith("win"):
        library_name = "fusionscript.dll"
        for executable in running_executables:
            candidates.append(executable.parent / library_name)
        candidates.extend([
            Path(os.environ["PROGRAMFILES"]) / "Blackmagic Design" / "DaVinci Resolve" / library_name
            if os.environ.get("PROGRAMFILES") else None,
            Path(os.environ["PROGRAMFILES(X86)"]) / "Blackmagic Design" / "DaVinci Resolve" / library_name
            if os.environ.get("PROGRAMFILES(X86)") else None,
        ])
        try:
            for base in (
                Path(os.environ["PROGRAMFILES"]) / "Blackmagic Design"
                if os.environ.get("PROGRAMFILES") else None,
                Path("C:/Program Files/Blackmagic Design"),
            ):
                if base and base.is_dir():
                    candidates.extend(base.glob("DaVinci Resolve*/" + library_name))
        except (OSError, KeyError):
            pass

        module_candidates = [
            Path(os.environ["PROGRAMDATA"]) / "Blackmagic Design" / "DaVinci Resolve"
            / "Support" / "Developer" / "Scripting" / "Modules"
            if os.environ.get("PROGRAMDATA") else None,
            Path("C:/ProgramData/Blackmagic Design/DaVinci Resolve/Support/Developer/Scripting/Modules"),
        ]
        for executable in running_executables:
            module_candidates.append(
                executable.parent.parent / "Support" / "Developer" / "Scripting" / "Modules"
            )
    elif sys.platform == "darwin":
        library_name = "fusionscript.so"
        candidates.extend([
            Path("/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion") / library_name,
            Path("/Applications/DaVinci Resolve Studio/DaVinci Resolve Studio.app/Contents/Libraries/Fusion") / library_name,
        ])
        module_candidates = [
            Path("/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules"),
        ]
        for executable in running_executables:
            resolve_app = Path(executable)
            while resolve_app.name and resolve_app.suffix != ".app":
                resolve_app = resolve_app.parent
            if resolve_app.suffix == ".app":
                candidates.append(resolve_app / "Contents/Libraries/Fusion" / library_name)
                module_candidates.append(
                    resolve_app / "Contents/Resources/Developer/Scripting/Modules"
                )
    else:
        library_name = "fusionscript.so"
        candidates.extend([
            Path("/opt/resolve/libs/Fusion") / library_name,
            Path("/opt/resolve/Developer/Shared/Libraries/fusionscript.so"),
        ])
        module_candidates = [
            Path("/opt/resolve/Developer/Scripting/Modules"),
        ]

    environment_library = os.environ.get("RESOLVE_SCRIPT_LIB")
    environment_modules = os.environ.get("RESOLVE_SCRIPT_MODULES")
    if environment_library:
        candidates.insert(0, Path(environment_library).expanduser())
    if environment_modules:
        module_candidates.insert(0, Path(environment_modules).expanduser())

    library = first_existing_file(candidates)
    modules = first_existing_file([
        candidate / "DaVinciResolveScript.py"
        if candidate else None
        for candidate in module_candidates
    ])

    if modules:
        modules = modules.parent

    return library, modules


dvr_script = None
dvr_script_error = None
dvr_script_last_attempt = 0


def load_resolve_script(force=False):
    """Load or retry DaVinciResolveScript with discovered and overridden paths."""
    global dvr_script, dvr_script_error, dvr_script_last_attempt

    now = time.monotonic()
    if dvr_script is not None:
        return dvr_script, None
    if not force and now - dvr_script_last_attempt < SCRIPT_RETRY_SECONDS:
        return None, dvr_script_error
    dvr_script_last_attempt = now

    library, modules = discover_resolve_paths()

    if modules is None:
        dvr_script_error = (
            "DaVinci Resolve scripting modules were not found. "
            "Install or repair the Resolve scripting support files."
        )
        return None, dvr_script_error

    if library is None:
        dvr_script_error = (
            "The Resolve fusionscript library was not found. "
            "Set RESOLVE_SCRIPT_LIB to its full DLL/SO path."
        )
        return None, dvr_script_error

    os.environ["RESOLVE_SCRIPT_LIB"] = str(library)
    module_dir = str(modules)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)

    try:
        importlib.invalidate_caches()
        if "DaVinciResolveScript" in sys.modules:
            del sys.modules["DaVinciResolveScript"]
        loaded_module = importlib.import_module("DaVinciResolveScript")
        scriptapp = getattr(loaded_module, "scriptapp", None)
        if not callable(scriptapp):
            raise AttributeError("The scripting module has no scriptapp() function")
        dvr_script = loaded_module
        dvr_script_error = None
        logger.info("Loaded Resolve scripting from %s", modules)
        return dvr_script, None
    except Exception as error:
        dvr_script_error = (
            f"Could not load DaVinciResolveScript from {modules}: "
            f"{type(error).__name__}: {error}"
        )
        logger.warning(dvr_script_error)
        return None, dvr_script_error

def get_resolve_activity():
    """Return the current project name and Resolve page, if available."""
    script_module, module_error = load_resolve_script()
    if script_module is None:
        return (
            "No Project Open",
            "Editing",
            module_error or "Resolve scripting module unavailable",
        )

    try:
        resolve = script_module.scriptapp("Resolve")
        if not resolve:
            return "No Project Open", "Editing", (
                "Resolve scripting is not accessible. Enable External scripting in "
                "Preferences > System > General."
            )

        project_name = "No Project Open"
        project_manager = resolve.GetProjectManager()
        if project_manager:
            current_project = project_manager.GetCurrentProject()
            if current_project:
                project_name = current_project.GetName() or "No Project Open"

        page = resolve.GetCurrentPage()
        if not isinstance(page, str) or not page:
            page = "Editing"

        return project_name, page, None
    except Exception as error:
        return "No Project Open", "Editing", (
            f"Unable to retrieve DaVinci Resolve state: {error}"
        )


def is_resolve_running():
    """Return whether a DaVinci Resolve process is active."""
    if sys.platform.startswith("win"):
        process_name = "resolve.exe"
    elif sys.platform == "darwin":
        process_name = "resolve"
    else:
        process_name = "resolve"

    try:
        for proc in psutil.process_iter(["name"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if name == process_name or (
                    sys.platform.startswith("win") and name.startswith("resolve")
                ):
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
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
        self.last_activity_error = None

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
            self.last_activity_error = None
            return

        if not self.resolve_was_running:
            self.session_start = int(time.time())
            self.last_payload = None

        self.resolve_was_running = True

        if not self.connect():
            return

        project_name, page, activity_error = get_resolve_activity()
        if activity_error and activity_error != self.last_activity_error:
            logger.warning(activity_error)
        elif not activity_error:
            if self.last_activity_error:
                logger.info("DaVinci Resolve scripting is accessible again.")
        self.last_activity_error = activity_error
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
    _, script_error = load_resolve_script(force=True)
    if script_error:
        logger.warning(script_error)
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