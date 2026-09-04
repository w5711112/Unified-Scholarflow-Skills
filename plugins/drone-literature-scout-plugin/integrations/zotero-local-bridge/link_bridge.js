var ZoteroObsidianLinkBridge = {
	BRIDGE_ORIGIN: "https://obsidian-link.invalid",
	id: null,
	version: null,
	rootURI: null,
	windowRecords: new Map(),

	init({ id, version, rootURI }) {
		this.id = id;
		this.version = version;
		this.rootURI = rootURI;
	},

	decodeBridgeURL(value) {
		try {
			let bridgeURL = new URL(value);
			if (
				bridgeURL.origin !== this.BRIDGE_ORIGIN
				|| bridgeURL.pathname !== "/open"
				|| bridgeURL.username
				|| bridgeURL.password
				|| bridgeURL.hash
				|| bridgeURL.searchParams.getAll("uri").length !== 1
			) {
				return null;
			}

			let target = bridgeURL.searchParams.get("uri");
			if (!target) {
				return null;
			}
			let obsidianURL = new URL(target);
			if (obsidianURL.protocol !== "obsidian:" || obsidianURL.host !== "open") {
				return null;
			}
			if (
				!obsidianURL.searchParams.get("vault")
				|| !obsidianURL.searchParams.get("file")
			) {
				return null;
			}
			return target;
		}
		catch (error) {
			Zotero.logError(error);
			return null;
		}
	},

	launchObsidianURI(obsidianURI) {
		try {
			let uri = Services.io.newURI(obsidianURI, null, null);
			let externalProtocolService =
				Components.classes[
					"@mozilla.org/uriloader/external-protocol-service;1"
				].getService(
					Components.interfaces.nsIExternalProtocolService
				);
			let handler = externalProtocolService.getProtocolHandlerInfo(
				"obsidian"
			);
			handler.preferredAction =
				Components.interfaces.nsIHandlerInfo.useSystemDefault;
			handler.alwaysAskBeforeHandling = false;
			handler.launchWithURI(uri, null);
			return true;
		}
		catch (error) {
			Zotero.logError(error);
			return false;
		}
	},

	addToWindow(window) {
		let pane = window?.ZoteroPane;
		if (!pane || this.windowRecords.has(window)) {
			return;
		}
		let originalLoadURI = pane.loadURI;
		if (typeof originalLoadURI !== "function") {
			return;
		}

		let bridge = this;
		let wrappedLoadURI = function (uris, event) {
			let list = typeof uris === "string"
				? [uris]
				: (Array.isArray(uris) ? uris : null);
			if (!list) {
				return originalLoadURI.call(this, uris, event);
			}

			let passthrough = [];
			for (let uri of list) {
				let obsidianURI = typeof uri === "string"
					? bridge.decodeBridgeURL(uri)
					: null;
				if (obsidianURI) {
					bridge.launchObsidianURI(obsidianURI);
				}
				else {
					passthrough.push(uri);
				}
			}

			if (!passthrough.length) {
				return;
			}
			let forwarded = typeof uris === "string" ? passthrough[0] : passthrough;
			return originalLoadURI.call(this, forwarded, event);
		};

		pane.loadURI = wrappedLoadURI;
		this.windowRecords.set(window, {
			pane,
			originalLoadURI,
			wrappedLoadURI,
		});
	},

	removeFromWindow(window) {
		let record = this.windowRecords.get(window);
		if (!record) {
			return;
		}
		if (record.pane.loadURI === record.wrappedLoadURI) {
			record.pane.loadURI = record.originalLoadURI;
		}
		this.windowRecords.delete(window);
	},

	addToAllWindows() {
		for (let window of Zotero.getMainWindows()) {
			this.addToWindow(window);
		}
	},

	removeFromAllWindows() {
		for (let window of Array.from(this.windowRecords.keys())) {
			this.removeFromWindow(window);
		}
	},
};