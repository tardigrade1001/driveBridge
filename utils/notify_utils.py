import subprocess
import threading

def _xml_escape(text: str) -> str:
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&apos;"))

def show_toast(title, message):
    """
    Shows a completely native Windows 10/11 Toast notification without needing any extra pip packages!
    It uses a silent PowerShell invoker in a background thread so it doesn't freeze Python.
    """
    def run():
        safe_title   = _xml_escape(str(title))
        safe_message = _xml_escape(str(message))
        ps_script = f"""
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
        $xml = "<toast><visual><binding template='ToastText02'><text id='1'>{safe_title}</text><text id='2'>{safe_message}</text></binding></visual></toast>"
        $doc = New-Object Windows.Data.Xml.Dom.XmlDocument
        $doc.LoadXml($xml)
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("DriveBridge").Show($doc)
        """
        try:
            # CREATE_NO_WINDOW prevents the black console box from flashing
            cflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                           creationflags=cflags)
        except Exception:
            pass

    # Never block the sync loop to render a UI toast
    threading.Thread(target=run, daemon=True).start()
