# Installation

In order to run the python script. This libraries must be installed in the system:

```bash
# Fedora
sudo dnf install python3-gobject
sudo dnf install python3-dbus

# Ubuntu
sudo apt install python3-gi
sudo apt install python3-dbus
```

**NOTE:** To find which package provides a file you can use this trick in Fedora

```bash
dnf provides qdbus-qt6
# or
dfn provides /usr/bin/qdbus-qt6
# or
dnf provides "qdbus*"
```

# DBus from python

To use DBus from python, the pydbus is used. You can find information
in:

[pydbus](https://github.com/LEW21/pydbus)

and a tutorial at:

[pydbus tutorial](https://github.com/LEW21/pydbus/blob/master/doc/tutorial.rst)

# Debuggin tips

## Querying KWin window information

Inquire KWin window info by selecting a window interactively with mouse:

```bash
qdbus6 org.kde.KWin /KWin org.kde.KWin.queryWindowInfo
```

Or query it by ID:

```bash
qdbus6 org.kde.KWin /KWin org.kde.KWin.getWindowInfo <window UUID here>
```

## KWin script debugging

Debug printing output from print("message") and console.log("message") commands goes to system journal from KWin scripts (embedded JavaScript inside the Python script), which can be tailed:

```bash
journalctl --user -u plasma-kwin_wayland.service -f -n 100
# or
journalctl --user _COMM=kwin_wayland -f -n 100
```

Helper function useful for listing object properties:

```js
function dumpObject(obj) {
  print("---- obj dump ----");
  for (var key in obj) {
    try {
      if (obj.hasOwnProperty(key)) {
        print(key + ": " + obj[key]);
      }
    } catch (e) {
      print(key + ": <error " + e + ">");
    }
  }
}
```

## DBus monitoring

```bash
dbus-monitor "destination=juan.sicilia.KWanata,path=/juan/sicilia/KWanata,interface=juan.sicilia.KWanata,member=DEBUG"
# or
dbus-monitor "destination=juan.sicilia.KWanata,path=/juan/sicilia/KWanata,interface=juan.sicilia.KWanata"
```

# Inspiration and acknowledgment

This tool could not be possible without these other tools:

[kanata](https://github.com/jtroo/kanata)
[FocusNotifier](https://github.com/c-massie/FocusNotifier)
[hyprkan](https://github.com/haithium/hyprkan)
[jumpkwapp](https://github.com/jasalt/jumpkwapp)
[ww-run-or-raise](https://github.com/academo/ww-run-raise)
[kdotools](https://github.com/tvidal-net/kdotool)
