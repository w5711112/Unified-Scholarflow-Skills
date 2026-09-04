var ZoteroObsidianLinkBridge;
var ZoteroNativeAnnotationBridge;

function log(message) {
	Zotero.debug("Zotero Local Bridge: " + message);
}

function install() {
	log("Installed");
}

async function startup({ id, version, rootURI }) {
	await Zotero.initializationPromise;
	Services.scriptloader.loadSubScript(rootURI + "link_bridge.js");
	Services.scriptloader.loadSubScript(rootURI + "annotation_bridge.js");
	ZoteroObsidianLinkBridge.init({ id, version, rootURI });
	await ZoteroNativeAnnotationBridge.init({ id, version, rootURI });
	ZoteroObsidianLinkBridge.addToAllWindows();
	log("Started " + version);
}

function onMainWindowLoad({ window }) {
	ZoteroObsidianLinkBridge?.addToWindow(window);
}

function onMainWindowUnload({ window }) {
	ZoteroObsidianLinkBridge?.removeFromWindow(window);
}

function shutdown() {
	ZoteroNativeAnnotationBridge?.shutdown();
	ZoteroObsidianLinkBridge?.removeFromAllWindows();
	ZoteroNativeAnnotationBridge = undefined;
	ZoteroObsidianLinkBridge = undefined;
	log("Stopped");
}

function uninstall() {
	log("Uninstalled");
}