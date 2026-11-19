from __future__ import annotations
import platform
import sys
import traceback

print("WinRemote brightness diagnostics")
print("=" * 36)
print(f"Windows: {platform.platform()}")
print(f"Python:  {sys.version.split()[0]} ({sys.executable})")

try:
    import screen_brightness_control as sbc
    print(f"screen-brightness-control: {getattr(sbc, '__version__', 'installed')}")
    for method in ("wmi", None):
        try:
            kwargs = {"method": method} if method else {}
            print(f"sbc.get_brightness({kwargs}): {sbc.get_brightness(**kwargs)}")
        except Exception as exc:
            print(f"sbc.get_brightness({method!r}) ERROR: {type(exc).__name__}: {exc}")
    try:
        print(f"sbc.list_monitors_info(): {sbc.list_monitors_info()}")
    except Exception as exc:
        print(f"sbc.list_monitors_info() ERROR: {type(exc).__name__}: {exc}")
except Exception as exc:
    print(f"screen_brightness_control import ERROR: {type(exc).__name__}: {exc}")

try:
    import pythoncom
    import wmi
    pythoncom.CoInitialize()
    try:
        c = wmi.WMI(namespace=r"root\wmi")
        brightness = c.WmiMonitorBrightness()
        methods = c.WmiMonitorBrightnessMethods()
        print(f"WMI WmiMonitorBrightness instances: {len(brightness)}")
        for item in brightness:
            print(f"  active={getattr(item, 'Active', None)}, current={getattr(item, 'CurrentBrightness', None)}, instance={getattr(item, 'InstanceName', '')}")
        print(f"WMI WmiMonitorBrightnessMethods instances: {len(methods)}")
        for item in methods:
            print(f"  active={getattr(item, 'Active', None)}, instance={getattr(item, 'InstanceName', '')}")
    finally:
        pythoncom.CoUninitialize()
except Exception as exc:
    print(f"Direct WMI ERROR: {type(exc).__name__}: {exc}")

print("\nNo brightness setting was changed by this diagnostic.")
