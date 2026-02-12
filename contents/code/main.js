// KWin script that forwards window focus/caption events to the KWanata DBus
// service. The Python service (focus_to_kanata.py) consumes these events to
// drive Kanata layer/virtual-key switching.

// Must match the DBus interface published by focus_to_kanata.py.
const SERVICE = "juan.sicilia.KWanata";
const PATH = "/juan/sicilia/KWanata";
const INTERFACE = "juan.sicilia.KWanata";

const DEBUG_METHOD = "DEBUG"
const FOCUS_EVENT_METHOD = "notifyFocusChanged";
const CAPTION_EVENT_METHOD = "notifyCaptionChanged";

// KDE 6 renamed clientActivated → windowActivated.
let windowActivated = workspace.windowActivated ?? workspace.clientActivated;

// Sends a DBus message.
// params:
//   method -- Method for the callDBus call.
//   msg -- Message to send.
function sendDBusMsg(method, msg) {
    callDBus(SERVICE, PATH, INTERFACE, method, msg);
}

// Sends a message to the DBus with the DEBUG_METHOD
// params:
//   msg -- Message to send.
function debug(msg) {
    sendDBusMsg(DEBUG_METHOD, msg);
}

// Sends the pid/name/class/caption of the window to de DBus.
// params:
//   method -- Method for the callDBus call.
//   window -- Window to get the info from.
// Build a "key: value" text block from window properties. The Python service
// parses this with DBUS_MSG_FIELD_RE to extract name/class/caption for rule
// matching.
function sendWindowData(method, window) {
    let msg = `
        pid: ${window.pid}
        name: ${window.resourceName}
        class: ${window.resourceClass}
        caption: ${window.caption}
    `;

    sendDBusMsg(method, msg);
}

// Responds to the windowActivated signal by sending the new activated window
// info via DBus.
windowActivated.connect(function(window) {
    // debug("Focus: " + window);
    if (!window)
        return;

    sendWindowData(FOCUS_EVENT_METHOD, window);
});

// Hook captionChange per window addition. Now every time a 
// window changes its caption, an event is sent. 
// Only sends the event if the window is the current active window.
workspace.windowAdded.connect(function(window) {

    window.captionChanged.connect(function() {
        // Only cares of the current active window.
        if (window === workspace.activeWindow) {
            // debug("Caption changed on window: " + window);
            sendWindowData(CAPTION_EVENT_METHOD, window);
        }
    });
});

