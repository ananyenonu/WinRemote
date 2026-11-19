# WinRemote

A local-network remote control for a Windows 10/11 laptop. The phone connects in its browser over Wi-Fi, Ethernet, or a supported Bluetooth PAN link.

## Install and start

This release adds an installable Android Progressive Web App (PWA) and HTTPS. It replaces the previous plain-HTTP URL, so update your phone bookmark to the new `https://` address shown by the connection-details window.

1. Extract the entire `WinRemote` folder to a permanent location, such as `Documents\WinRemote`. Do not move or delete it after installing shortcuts.
2. Double-click **Install WinRemote.bat** once. This installs dependencies, creates a `WinRemote` shortcut on the Desktop, adds a quiet logon startup shortcut, and starts the server in the background.
3. A connection-details window shows the HTTPS phone URL, pairing code, and path to the local CA certificate. Before opening the URL on Android, copy the `.cer` file to the phone and install it as a CA certificate in Android Settings (search Settings for “Install a certificate”). Then open the HTTPS URL in Chrome and pair with the six-digit code. Chrome should then offer **Install app** in its three-dot menu. The installed app opens in standalone mode with the WinRemote icon. If Chrome still shows a certificate warning, do not bypass it; verify that the correct WinRemote CA certificate was installed and that the URL IP matches the current laptop IP.
4. Bookmark that URL on your phone. In the pairing page, leave **Remember this phone** checked only on your own phone. The browser reconnects automatically while the server's current session remains valid.

## Everyday use

- Double-click the Desktop **WinRemote** shortcut to start it or show the current URL and pairing code. It runs without a terminal window.
- WinRemote also starts quietly when you sign in to Windows.
- In the Start Menu, open **WinRemote > Show connection details** to retrieve the current URL and pairing code.
- Use **WinRemote > Stop WinRemote** to stop the background server. You can also run `Stop WinRemote.bat` from the app folder.
- The server runs only after your Windows user signs in. It is not a Windows service and does not run at the Windows lock/sign-in screen.

## Bookmarking the URL

Yes. Bookmark the Wi-Fi URL shown in the connection-details window, for example `https://192.168.1.25:8765`. It will keep working as long as the laptop keeps the same local IP address and WinRemote is running. For a stable bookmark, create a DHCP reservation for the laptop in your router's LAN/DHCP settings. If your router assigns a different IP, open **Show connection details** and update the bookmark.

The pairing code is needed for the first pairing. If **Remember this phone** is enabled, the browser stores its session token and WinRemote stores only a hash of that token in your Windows user profile. The phone reconnects automatically across browser tabs and Windows restarts. Use **Disconnect** in the app to revoke that remembered phone. If you lose the phone or clear its browser storage before disconnecting, stop WinRemote and delete `%LOCALAPPDATA%\WinRemote\trusted_devices.json` to revoke all remembered phones, then start WinRemote again. If you uncheck the option, the session lasts only for the current browser tab and current server process.

## Requirements

- Windows 10 or Windows 11
- Python 3.10 or newer
- Phone and laptop on the same trusted Wi-Fi network, or a supported Bluetooth PAN link

## Touchpad and desktop controls

- **One finger:** move the Windows pointer; tap to left-click.
- **Two fingers:** scroll vertically or horizontally in browsers that expose multi-touch Pointer Events.
- **Previous desktop / Next desktop:** use the dedicated buttons below the touchpad. They send the native Windows shortcuts `Win` + `Ctrl` + `Left` and `Win` + `Ctrl` + `Right`.
- Three-finger desktop switching is intentionally disabled. Use the explicit desktop buttons for reliable switching.

## Bluetooth

Bluetooth PAN is network-over-Bluetooth, not direct Bluetooth HID. Android support depends on phone and Windows adapter behavior. Wi-Fi is recommended for best reliability. The browser app cannot turn itself into a generic Bluetooth mouse/keyboard device.

## Security and Windows sign-in

- The app accepts private/local-network clients only, requires a six-digit pairing code, applies failed-attempt throttling, and uses a temporary session token.
- The connection-details file containing the pairing code is stored in the current Windows user's `%LOCALAPPDATA%\WinRemote` folder. It is not exposed through a web endpoint.
- Use only on a trusted private network. Do not port-forward port `8765`, expose it to the internet, or share the pairing code.
- **Lock** locks the Windows session. WinRemote cannot enter your Windows PIN on the sign-in screen. Windows protects credential interfaces against remote/automated keystroke injection. Unlock locally, or use a separately configured supported remote-desktop solution. Do not send your Windows PIN through this web app.
- WinRemote now serves the app over HTTPS using a private local certificate authority. Install `%LOCALAPPDATA%\WinRemote\WinRemote-Root-CA.cer` on your Android phone as a CA certificate before using the HTTPS URL. The CA private key stays on the laptop. Treat this CA certificate as a trust credential: install only the certificate generated by your own WinRemote instance, and never share the matching private key. If you reset the CA files, install the new CA certificate on the phone. The app must run in your signed-in desktop session. It cannot start before sign-in or control the Windows lock screen.
- Brightness control uses the built-in Windows WMI monitor-brightness interface first, then tries supported monitor backends. Windows must expose a compatible brightness controller. Run **Diagnose Brightness.bat** if the slider says Unavailable; it creates `WinRemote-brightness-diagnostic.txt` on your Desktop.
- Some elevated applications may ignore simulated input unless WinRemote runs at matching privilege. Do not run as Administrator unless strictly necessary.

## Troubleshooting

- If the shortcut does not start the server, inspect `%LOCALAPPDATA%\WinRemote\launcher-error.log` and `server.log`.
- If the phone cannot connect, confirm both devices are on the same Wi-Fi, disable guest-network/client isolation, and allow Python through Windows Defender Firewall on **Private networks only** for TCP port `8765`. Do not expose or port-forward this port to the internet.
- If the bookmark stops working, check whether the laptop's local IP changed. Create a router DHCP reservation if needed.
- If a stale browser session appears after restarting WinRemote, reopen the bookmarked URL and pair using the new code from **Show connection details**.


## Brightness troubleshooting

- After updating this version, run **Install WinRemote.bat** again so the WMI dependencies are installed into the WinRemote virtual environment.
- Stop and restart WinRemote after installation.
- If brightness is still unavailable, run **Diagnose Brightness.bat** and inspect `WinRemote-brightness-diagnostic.txt` on your Desktop. The report does not change brightness settings.
- If Windows Settings > System > Display also has no brightness slider, install/update the HP display, chipset, and graphics drivers. External monitors may require DDC/CI support to be enabled in the monitor menu.

