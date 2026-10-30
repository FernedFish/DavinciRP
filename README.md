<div align = "center">

# DavinciRP

A custom Discord Rich Presence plugin using **python**

</div>

# Initial steps

1. Create a Discord application from the [Discord Developer Portal](https://discord.com/developers/applications)

    - Adjust to your liking how it's displayed on Discord

2. Set up your development enviroment

    ```
    pip install pypresence psutil
    
    ```

    `pypresence` is an independent lightweight library that communicates with the local Discord client

3. Configure Davinci Resolve Scripting Environment

    a. Open DaVinci Resolve.

    b. Go to Preferences > General > External scripting using.

    c. Set it to Local (or Local Network if running scripts remotely).

    d. Ensure your system environment variables point correctly to the Resolve scripting libraries so Python can import DaVinciResolveScript


4. Enjoy your Davinci Resolve Rich Presence!

## How heavy is it?

15 - 45 MB of RAM Usage

---

Note: if you want the script to be standalone without needing to keep a CMD or Terminal open, bundle it into an exe with PyInstaller

```
pip install pyinstaller
```

then 

```
pyinstaller --noconsole --onefile resolve_rpc.py
```
---

## Author

Rafael Victoriano
