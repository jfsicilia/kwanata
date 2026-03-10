// KWin script that raises (or cycles) a window matching a given class/caption.
// Injected as a temporary script by kwanata.py each time a run-or-raise action
// is triggered. Sends the result back to the KWanata DBus service.
//
// __<NAME>__ are placeholders that will be replaced by kwanata.py
//
// This code was copied and modified from ww raise or run project (apache 2.0 
// licensed). Many thanks to contributors.
const KWANATA_SERVICE = "com.pyroflexia.KWanata";
const KWANATA_PATH = "/com/pyroflexia/KWanata";
const KWANATA_INTERFACE = "com.pyroflexia.KWanata";

function kwinActivateClient(clientClass, clientCaption) {
    // Little hack to be KDE5 and KDE6 compatible.
    let clients = workspace.clientList ? workspace.clientList() : workspace.windowList();
    let activeWindow = workspace.activeClient || workspace.activeWindow;

    // Compile regular expressions.
    let clientClassRE = new RegExp(clientClass || '', 'i');
    let clientCaptionRE = new RegExp(clientCaption || '', 'i');
    let matchingClients = [];
    for (var i = 0; i < clients.length; i++) {
        let client = clients[i];
        if (clientClassRE.exec(client.resourceClass) && clientCaptionRE.exec(client.caption)) {
            matchingClients.push(client);
        }
    }
    if (matchingClients.length === 0) {
        sendRaiseResult(false, clientClass, clientCaption);
        return;
    }

    if (matchingClients.length === 1) {
        if (activeWindow !== matchingClients[0]) {
            setActiveClient(matchingClients[0]);
        }
        sendRaiseResult(true, clientClass, clientCaption);
        return;
    }

    // Check if the active window is one of the matching windows
    let activeIsMatching = false;
    for (var j = 0; j < matchingClients.length; j++) {
        if (activeWindow === matchingClients[j]) {
            activeIsMatching = true;
            break;
        }
    }
    // Always sort by stacking order
    matchingClients.sort(function (a, b) {
        return a.stackingOrder - b.stackingOrder;
    });
    // Activate new window.
    if (activeIsMatching) {
        // We're already in this app - cycle through windows (pick first)
        const client = matchingClients[0];
        setActiveClient(client);
    } else {
        // We're switching from another app - pick most recently active (last)
        const client = matchingClients[matchingClients.length - 1];
        setActiveClient(client);
    }
    sendRaiseResult(true, clientClass, clientCaption);
}

function setActiveClient(client) {
    if (workspace.activeClient !== undefined) {
        workspace.activeClient = client;
    } else {
        workspace.activeWindow = client;
    }
}

function sendRaiseResult(success, clientClass, clientCaption) {
    let msg = "class: " + clientClass + "\ncaption: " + clientCaption + "\nsuccess: " + success;
    callDBus(KWANATA_SERVICE, KWANATA_PATH, KWANATA_INTERFACE, "notifyRaiseResult", msg);
}

kwinActivateClient('__CLASS__', '__CAPTION__');
