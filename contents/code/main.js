const SERVICE = "juan.sicilia.KWanata";
const PATH = "/juan/sicilia/KWanata";
const INTERFACE = "juan.sicilia.KWanata";

const DEBUG_METHOD = "DEBUG"
const FOCUS_EVENT_METHOD = "notifyFocusChanged";
const CAPTION_EVENT_METHOD = "notifyCaptionChanged";

// .windowActivated for KDE 6, .clientActivated for KDE 5.
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

// Responds to the windowAdded signal by attaching a function to Respond 
// to the captionChanged signal by sending the window info via DBus.
workspace.windowAdded.connect(function(window) {
    // debug("Added window:" + window);

    window.captionChanged.connect(function() {
        // Only cares of the current active window.
        if (window === workspace.activeWindow) {
            // debug("Caption changed on window: " + window);
            sendWindowData(CAPTION_EVENT_METHOD, window);
        }
    });
});

