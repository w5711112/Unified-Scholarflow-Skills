const FIXTURE_ENDPOINT = "/test/zotero-local-bridge/fixture";
const FAILURE_ENDPOINT = "/test/zotero-local-bridge/failure";
const RESULT_FILE = "zotero-local-bridge-integration-fixture.json";
let fixtureAttachment = null;
let originalItemSave = null;
let itemPrototypeHadOwnSave = false;
let saveCallCount = 0;
let failOnSaveCall = null;

function jsonResponse(status, payload) {
	return [status, "application/json", JSON.stringify(payload)];
}

async function annotationState() {
	if (!fixtureAttachment) return [];
	const annotations = fixtureAttachment.getAnnotations();
	for (const annotation of annotations) {
		await annotation.loadDataType("tags");
	}
	return annotations.map(annotation => ({
		key: annotation.key,
		type: annotation.annotationType,
		comment: annotation.annotationComment || "",
		color: annotation.annotationColor,
		tags: annotation.getTags().map(entry => (
			typeof entry === "string" ? entry : entry.tag
		)),
	}));
}

async function writeFixtureState(manualKey) {
	const path = PathUtils.join(PathUtils.profileDir, RESULT_FILE);
	await IOUtils.writeUTF8(
		path,
		JSON.stringify({
			library_id: Zotero.Libraries.userLibraryID,
			attachment_key: fixtureAttachment.key,
			manual_annotation_key: manualKey,
			attachment_content_type: fixtureAttachment.attachmentContentType,
			annotations: await annotationState(),
		}),
		{ tmpPath: path + ".tmp" },
	);
}

async function createFixture() {
	const pdfPath = PathUtils.join(
		PathUtils.profileDir,
		"zotero-local-bridge-integration-fixture.pdf",
	);
	const pdf = [
		"%PDF-1.4",
		"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj",
		"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj",
		"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj",
		"xref",
		"0 4",
		"0000000000 65535 f ",
		"trailer<</Root 1 0 R/Size 4>>",
		"startxref",
		"0",
		"%%EOF",
	].join("\n");
	await IOUtils.writeUTF8(pdfPath, pdf, { tmpPath: pdfPath + ".tmp" });
	fixtureAttachment = await Zotero.Attachments.importFromFile({
		file: pdfPath,
		libraryID: Zotero.Libraries.userLibraryID,
		title: "Zotero Local Bridge Integration Fixture",
		contentType: "application/pdf",
	});
	const manualKey = Zotero.DataObjectUtilities.generateKey();
	await Zotero.Annotations.saveFromJSON(fixtureAttachment, {
		key: manualKey,
		type: "highlight",
		text: "manual fixture",
		comment: "manual fixture",
		color: "#ffd400",
		pageLabel: "1",
		sortIndex: "00000|000000|00001",
		position: {
			pageIndex: 0,
			rects: [[1, 1, 2, 2]],
		},
		tags: [],
	});
	await writeFixtureState(manualKey);
}

function restoreItemSave() {
	if (originalItemSave) {
		if (itemPrototypeHadOwnSave) {
			Zotero.Item.prototype.save = originalItemSave;
		} else {
			delete Zotero.Item.prototype.save;
		}
	}
	originalItemSave = null;
	itemPrototypeHadOwnSave = false;
	saveCallCount = 0;
	failOnSaveCall = null;
}

class FixtureEndpoint {
	constructor() {
		this.supportedMethods = ["GET"];
		this.allowRequestsFromUnsafeWebContent = true;
	}

	async init(_request) {
		if (!fixtureAttachment) {
			return jsonResponse(503, { ready: false });
		}
		return jsonResponse(200, {
			ready: true,
			library_id: Zotero.Libraries.userLibraryID,
			attachment_key: fixtureAttachment.key,
			annotations: await annotationState(),
		});
	}
}

class FailureEndpoint {
	constructor() {
		this.supportedMethods = ["POST"];
		this.supportedDataTypes = ["application/json"];
		this.allowRequestsFromUnsafeWebContent = true;
	}

	init(request) {
		const action = request.data && request.data.action;
		if (action === "disarm") {
			restoreItemSave();
			return jsonResponse(200, { armed: false });
		}
		if (action !== "arm" || request.data.fail_on_call !== 2) {
			return jsonResponse(400, { error: "expected arm with fail_on_call=2" });
		}
		restoreItemSave();
		const prototype = Zotero.Item.prototype;
		itemPrototypeHadOwnSave = Object.prototype.hasOwnProperty.call(prototype, "save");
		originalItemSave = prototype.save;
		saveCallCount = 0;
		failOnSaveCall = 2;
		prototype.save = async function (...args) {
			const isFixtureAnnotation = this.isAnnotation()
				&& fixtureAttachment
				&& this.parentID === fixtureAttachment.id;
			if (isFixtureAnnotation) {
				saveCallCount += 1;
				if (saveCallCount === failOnSaveCall) {
					throw new Error("injected integration failure");
				}
			}
			return originalItemSave.apply(this, args);
		};
		return jsonResponse(200, { armed: true, fail_on_call: failOnSaveCall });
	}
}

async function startup() {
	await Zotero.initializationPromise;
	Zotero.Server.Endpoints[FIXTURE_ENDPOINT] = FixtureEndpoint;
	Zotero.Server.Endpoints[FAILURE_ENDPOINT] = FailureEndpoint;
	await createFixture();
}

function shutdown() {
	restoreItemSave();
	if (Zotero.Server.Endpoints[FIXTURE_ENDPOINT] === FixtureEndpoint) {
		delete Zotero.Server.Endpoints[FIXTURE_ENDPOINT];
	}
	if (Zotero.Server.Endpoints[FAILURE_ENDPOINT] === FailureEndpoint) {
		delete Zotero.Server.Endpoints[FAILURE_ENDPOINT];
	}
	fixtureAttachment = null;
}

function install() {}
function uninstall() {}
