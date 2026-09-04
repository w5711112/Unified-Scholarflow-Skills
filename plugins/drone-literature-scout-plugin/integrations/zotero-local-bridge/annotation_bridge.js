var ZoteroNativeAnnotationBridge = (() => {
	const SCHEMA_VERSION = 1;
	const MAX_BATCH_SIZE = 100;
	const MAX_COMMENT_LENGTH = 4000;
	const KEY_PATTERN = /^[A-Z0-9]{8}$/;
	const ID_PATTERN = /^[A-Za-z0-9._:-]{1,128}$/;
	const DIGEST_PATTERN = /^[a-f0-9]{64}$/;
	const HEALTH_PATH = "/zotero-local-bridge/v1/health";
	const PREFLIGHT_PATH = "/zotero-local-bridge/v1/annotations/preflight";
	const APPLY_PATH = "/zotero-local-bridge/v1/annotations/apply";
	const STABLE_TAG_PREFIX = "zotero-local-bridge:stable-id:";
	const SECRET_PREF = "extensions.zotero-local-bridge.profile-secret";
	const AUTH_FOLDER = "zotero-local-bridge";
	const AUTH_TOKEN_FILE = "auth-token";
	let security = null;
	let runtime = null;
	let registeredServer = null;
	let registeredEndpoints = null;

	function protocolError(status, code, message) {
		const error = new Error(message);
		error.status = status;
		error.code = code;
		return error;
	}

	function isPlainObject(value) {
		return value !== null && typeof value === "object" && !Array.isArray(value);
	}

	function assertObject(value, label) {
		if (!isPlainObject(value)) {
			throw protocolError(400, "invalid_object", label + " must be an object");
		}
	}

	function assertAllowedKeys(value, allowed, label) {
		assertObject(value, label);
		for (const key of Object.keys(value)) {
			if (!allowed.includes(key)) {
				throw protocolError(400, "unknown_field", label + " contains unknown field: " + key);
			}
		}
	}

	function assertString(value, label, minLength, maxLength, pattern) {
		if (typeof value !== "string" || value.length < minLength || value.length > maxLength) {
			throw protocolError(422, "invalid_string", label + " has an invalid length");
		}
		if (pattern && !pattern.test(value)) {
			throw protocolError(422, "invalid_string", label + " has an invalid format");
		}
	}

	function assertInteger(value, label, minimum) {
		if (!Number.isSafeInteger(value) || value < minimum) {
			throw protocolError(422, "invalid_integer", label + " must be an integer >= " + minimum);
		}
	}

	function canonicalJSONStringify(value) {
		function normalize(current) {
			if (current === null || typeof current === "string" || typeof current === "boolean") {
				return current;
			}
			if (typeof current === "number") {
				if (!Number.isFinite(current)) {
					throw protocolError(422, "invalid_number", "non-finite numbers are not allowed");
				}
				return current;
			}
			if (Array.isArray(current)) {
				return current.map(normalize);
			}
			if (isPlainObject(current)) {
				const normalized = {};
				for (const key of Object.keys(current).sort()) {
					if (current[key] === undefined) {
						throw protocolError(400, "undefined_field", "undefined values are not allowed");
					}
					normalized[key] = normalize(current[key]);
				}
				return normalized;
			}
			throw protocolError(400, "invalid_json_value", "unsupported JSON value");
		}
		return JSON.stringify(normalize(value));
	}

	function normalizeKey(value, label) {
		assertString(value, label, 8, 8, KEY_PATTERN);
		return value;
	}

	function normalizePosition(position, pageIndex) {
		assertAllowedKeys(position, ["pageIndex", "rects"], "annotation.position");
		assertInteger(position.pageIndex, "annotation.position.pageIndex", 0);
		if (position.pageIndex !== pageIndex) {
			throw protocolError(422, "page_mismatch", "position pageIndex must equal annotation page_index");
		}
		if (!Array.isArray(position.rects) || position.rects.length < 1 || position.rects.length > 100) {
			throw protocolError(422, "invalid_rects", "annotation.position.rects must contain 1-100 rectangles");
		}
		const rects = position.rects.map((rect) => {
			if (!Array.isArray(rect) || rect.length !== 4 || rect.some((number) => !Number.isFinite(number))) {
				throw protocolError(422, "invalid_rect", "each annotation rectangle must contain four finite numbers");
			}
			if (rect[0] >= rect[2] || rect[1] >= rect[3]) {
				throw protocolError(422, "invalid_rect", "annotation rectangle bounds must be ordered");
			}
			return rect.slice();
		});
		return { pageIndex: position.pageIndex, rects };
	}

	function defaultSortIndex(pageIndex, position) {
		const rect = position.rects[0];
		const page = String(pageIndex).slice(0, 5).padStart(5, "0");
		const offset = "000000";
		const top = String(Math.min(99999, Math.max(0, Math.floor(rect[1]))))
			.padStart(5, "0");
		return [page, offset, top].join("|");
	}

	function normalizeAnnotation(annotation) {
		assertAllowedKeys(
			annotation,
			[
				"stable_id", "native_key", "type", "page_index", "page_label",
				"sort_index", "position", "color", "comment", "text",
			],
			"annotation",
		);
		assertString(annotation.stable_id, "annotation.stable_id", 1, 128, ID_PATTERN);
		if (annotation.type !== "highlight" && annotation.type !== "image") {
			throw protocolError(422, "unsupported_annotation_type", "only highlight and image annotations are supported");
		}
		assertInteger(annotation.page_index, "annotation.page_index", 0);
		assertString(annotation.color, "annotation.color", 7, 7, /^#[0-9a-fA-F]{6}$/);
		if (typeof annotation.comment !== "string" || annotation.comment.length > MAX_COMMENT_LENGTH) {
			throw protocolError(422, "invalid_comment", "annotation.comment exceeds the allowed length");
		}
		if (annotation.type === "highlight" && annotation.text !== undefined) {
			assertString(annotation.text, "annotation.text", 0, 20000);
		}
		if (annotation.type === "image" && annotation.text !== undefined) {
			throw protocolError(422, "unexpected_text", "image annotations must not contain text");
		}
		const position = normalizePosition(annotation.position, annotation.page_index);
		const pageLabel = annotation.page_label === undefined
			? String(annotation.page_index + 1)
			: annotation.page_label;
		const sortIndex = annotation.sort_index;
		assertString(pageLabel, "annotation.page_label", 1, 100);
		assertString(
			sortIndex,
			"annotation.sort_index",
			1,
			100,
			/^[0-9]{5}\|[0-9]{6}\|[0-9]{5}$/,
		);
		const normalized = {
			stable_id: annotation.stable_id,
			type: annotation.type,
			page_index: annotation.page_index,
			page_label: pageLabel,
			sort_index: sortIndex,
			position,
			color: annotation.color.toLowerCase(),
			comment: annotation.comment,
		};
		if (annotation.type === "highlight") normalized.text = annotation.text || "";
		if (annotation.native_key !== undefined) {
			normalized.native_key = normalizeKey(annotation.native_key, "annotation.native_key");
		}
		return normalized;
	}

	function normalizeUniqueKeys(keys, label) {
		if (!Array.isArray(keys) || keys.length > MAX_BATCH_SIZE) {
			throw protocolError(422, "invalid_key_list", label + " must be an array of at most " + MAX_BATCH_SIZE + " keys");
		}
		const normalized = keys.map((key) => normalizeKey(key, label));
		if (new Set(normalized).size !== normalized.length) {
			throw protocolError(422, "duplicate_key", label + " contains duplicate keys");
		}
		return normalized;
	}

	function validateRequest(body, mode) {
		if (mode !== "preflight" && mode !== "apply") {
			throw protocolError(400, "invalid_mode", "mode must be preflight or apply");
		}
		const commonKeys = [
			"schema_version",
			"operation_id",
			"library",
			"attachment",
			"annotations",
			"allowed_native_keys",
			"deletions",
		];
		const allowedKeys = mode === "apply"
			? commonKeys.concat(["plan_digest", "snapshot_digest", "receipt"])
			: commonKeys;
		assertAllowedKeys(body, allowedKeys, "request");
		if (body.schema_version !== SCHEMA_VERSION) {
			throw protocolError(400, "unsupported_schema", "schema_version must be " + SCHEMA_VERSION);
		}
		assertString(body.operation_id, "operation_id", 1, 128, ID_PATTERN);

		assertAllowedKeys(body.library, ["type", "id"], "library");
		if (body.library.type !== "user") {
			throw protocolError(422, "user_library_required", "only the user library is supported");
		}
		assertInteger(body.library.id, "library.id", 1);

		assertAllowedKeys(body.attachment, ["key", "content_type"], "attachment");
		const attachmentKey = normalizeKey(body.attachment.key, "attachment.key");
		if (body.attachment.content_type !== "application/pdf") {
			throw protocolError(422, "pdf_required", "attachment must be a PDF");
		}

		if (!Array.isArray(body.annotations) || !Array.isArray(body.deletions)) {
			throw protocolError(400, "invalid_plan", "annotations and deletions must be arrays");
		}
		if (body.annotations.length + body.deletions.length > MAX_BATCH_SIZE) {
			throw protocolError(422, "batch_too_large", "a batch may contain at most " + MAX_BATCH_SIZE + " operations");
		}
		const annotations = body.annotations.map(normalizeAnnotation);
		const stableIDs = annotations.map((annotation) => annotation.stable_id);
		if (new Set(stableIDs).size !== stableIDs.length) {
			throw protocolError(422, "duplicate_stable_id", "annotation stable IDs must be unique");
		}

		const allowedNativeKeys = normalizeUniqueKeys(body.allowed_native_keys, "allowed_native_keys");
		const allowedSet = new Set(allowedNativeKeys);
		for (const annotation of annotations) {
			if (annotation.native_key && !allowedSet.has(annotation.native_key)) {
				throw protocolError(409, "native_key_not_allowed", "an update key is not explicitly allowed");
			}
		}

		const deletions = body.deletions.map((deletion) => {
			assertAllowedKeys(deletion, ["native_key", "before_fingerprint"], "deletion");
			const nativeKey = normalizeKey(deletion.native_key, "deletion.native_key");
			assertString(deletion.before_fingerprint, "deletion.before_fingerprint", 64, 64, DIGEST_PATTERN);
			if (!allowedSet.has(nativeKey)) {
				throw protocolError(409, "native_key_not_allowed", "a deletion key is not explicitly allowed");
			}
			return { native_key: nativeKey, before_fingerprint: deletion.before_fingerprint };
		});
		const deletionKeys = deletions.map((deletion) => deletion.native_key);
		if (new Set(deletionKeys).size !== deletionKeys.length) {
			throw protocolError(422, "duplicate_deletion", "deletion keys must be unique");
		}

		const normalized = {
			schema_version: SCHEMA_VERSION,
			operation_id: body.operation_id,
			library: { type: "user", id: body.library.id },
			attachment: { key: attachmentKey, content_type: "application/pdf" },
			annotations,
			allowed_native_keys: allowedNativeKeys,
			deletions,
		};
		if (mode === "apply") {
			assertString(body.plan_digest, "plan_digest", 64, 64, DIGEST_PATTERN);
			assertString(body.snapshot_digest, "snapshot_digest", 64, 64, DIGEST_PATTERN);
			assertString(body.receipt, "receipt", 1, 4096);
			normalized.plan_digest = body.plan_digest;
			normalized.snapshot_digest = body.snapshot_digest;
			normalized.receipt = body.receipt;
		}
		return normalized;
	}

	function requireSecurity() {
		if (!security) {
			throw protocolError(503, "security_not_initialized", "bridge security is not initialized");
		}
		return security;
	}

	function configureSecurity(options) {
		assertAllowedKeys(options, ["getProfileSecret", "sha256Hex", "hmacSha256Hex", "now"], "security options");
		for (const name of ["getProfileSecret", "sha256Hex", "hmacSha256Hex", "now"]) {
			if (typeof options[name] !== "function") {
				throw protocolError(500, "invalid_security_provider", name + " must be a function");
			}
		}
		security = { ...options };
	}

	function profileSecret() {
		const profileMaterial = requireSecurity().getProfileSecret();
		assertString(profileMaterial, "profile secret", 64, 64, DIGEST_PATTERN);
		return profileMaterial;
	}

	function derivedKey(label) {
		return requireSecurity().hmacSha256Hex(profileSecret(), label);
	}

	function getAuthenticationToken() {
		return derivedKey("zotero-local-bridge:authentication:v1");
	}

	function constantTimeEqual(left, right) {
		if (typeof left !== "string" || typeof right !== "string" || left.length !== right.length) {
			return false;
		}
		let difference = 0;
		for (let index = 0; index < left.length; index += 1) {
			difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
		}
		return difference === 0;
	}

	function verifyAuthenticationToken(candidate) {
		return constantTimeEqual(candidate, getAuthenticationToken());
	}

	function annotationFingerprint(attachmentKey, annotation) {
		normalizeKey(attachmentKey, "attachment key");
		const normalized = normalizeAnnotation(annotation);
		const payload = {
			attachment_key: attachmentKey,
			stable_id: normalized.stable_id,
			type: normalized.type,
			page_index: normalized.page_index,
			page_label: normalized.page_label,
			sort_index: normalized.sort_index,
			position: normalized.position,
			color: normalized.color,
			comment: normalized.comment,
			text: normalized.text || "",
		};
		return requireSecurity().sha256Hex(canonicalJSONStringify(payload));
	}

	function planDigest(request) {
		const normalized = validateRequest(request, "preflight");
		return requireSecurity().sha256Hex(canonicalJSONStringify(normalized));
	}

	function validateReceiptPayload(payload) {
		assertAllowedKeys(
			payload,
			["operation_id", "plan_digest", "snapshot_digest", "expiry", "schema_version"],
			"receipt payload",
		);
		assertString(payload.operation_id, "receipt operation_id", 1, 128, ID_PATTERN);
		assertString(payload.plan_digest, "receipt plan_digest", 64, 64, DIGEST_PATTERN);
		assertString(payload.snapshot_digest, "receipt snapshot_digest", 64, 64, DIGEST_PATTERN);
		assertInteger(payload.expiry, "receipt expiry", 0);
		if (payload.schema_version !== SCHEMA_VERSION) {
			throw protocolError(400, "unsupported_schema", "receipt schema_version is unsupported");
		}
		return {
			operation_id: payload.operation_id,
			plan_digest: payload.plan_digest,
			snapshot_digest: payload.snapshot_digest,
			expiry: payload.expiry,
			schema_version: SCHEMA_VERSION,
		};
	}

	function asciiToHex(value) {
		let output = "";
		for (let index = 0; index < value.length; index += 1) {
			const code = value.charCodeAt(index);
			if (code > 0x7f) {
				throw protocolError(400, "non_ascii_receipt", "receipt fields must be ASCII");
			}
			output += code.toString(16).padStart(2, "0");
		}
		return output;
	}

	function hexToAscii(value) {
		if (!/^(?:[a-f0-9]{2})+$/.test(value)) {
			throw protocolError(400, "invalid_receipt", "receipt payload is not valid hex");
		}
		let output = "";
		for (let index = 0; index < value.length; index += 2) {
			output += String.fromCharCode(Number.parseInt(value.slice(index, index + 2), 16));
		}
		return output;
	}

	function signReceipt(input) {
		const payload = validateReceiptPayload(input);
		if (payload.expiry <= requireSecurity().now()) {
			throw protocolError(409, "expired_receipt", "receipt expiry must be in the future");
		}
		const serialized = canonicalJSONStringify(payload);
		const key = derivedKey("zotero-local-bridge:receipt-signing:v1");
		const signature = requireSecurity().hmacSha256Hex(key, serialized);
		return asciiToHex(serialized) + "." + signature;
	}

	function verifyReceipt(receipt, expected) {
		try {
			if (typeof receipt !== "string" || receipt.length > 4096) {
				return false;
			}
			const parts = receipt.split(".");
			if (parts.length !== 2 || !DIGEST_PATTERN.test(parts[1])) {
				return false;
			}
			const payload = validateReceiptPayload(JSON.parse(hexToAscii(parts[0])));
			const expectedPayload = validateReceiptPayload(expected);
			if (payload.expiry <= requireSecurity().now()) {
				return false;
			}
			const serialized = canonicalJSONStringify(payload);
			if (!constantTimeEqual(serialized, canonicalJSONStringify(expectedPayload))) {
				return false;
			}
			const key = derivedKey("zotero-local-bridge:receipt-signing:v1");
			const signature = requireSecurity().hmacSha256Hex(key, serialized);
			return constantTimeEqual(signature, parts[1]);
		} catch (_) {
			return false;
		}
	}

	function bytesToHex(bytes) {
		return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
	}

	function zoteroSHA256Bytes(bytes) {
		const hash = Components.classes["@mozilla.org/security/hash;1"]
			.createInstance(Components.interfaces.nsICryptoHash);
		hash.init(hash.SHA256);
		hash.update(bytes, bytes.length);
		const binary = hash.finish(false);
		return Uint8Array.from(binary, (character) => character.charCodeAt(0));
	}

	function zoteroSHA256Hex(value) {
		return bytesToHex(zoteroSHA256Bytes(new TextEncoder().encode(value)));
	}

	function zoteroHMACSHA256Hex(key, value) {
		let keyBytes = new TextEncoder().encode(key);
		if (keyBytes.length > 64) keyBytes = zoteroSHA256Bytes(keyBytes);
		const block = new Uint8Array(64);
		block.set(keyBytes);
		const innerPad = block.map((byte) => byte ^ 0x36);
		const outerPad = block.map((byte) => byte ^ 0x5c);
		const valueBytes = new TextEncoder().encode(value);
		const innerInput = new Uint8Array(innerPad.length + valueBytes.length);
		innerInput.set(innerPad);
		innerInput.set(valueBytes, innerPad.length);
		const innerHash = zoteroSHA256Bytes(innerInput);
		const outerInput = new Uint8Array(outerPad.length + innerHash.length);
		outerInput.set(outerPad);
		outerInput.set(innerHash, outerPad.length);
		return bytesToHex(zoteroSHA256Bytes(outerInput));
	}

	function randomProfileSecret() {
		const generator = Components.classes["@mozilla.org/security/random-generator;1"]
			.createInstance(Components.interfaces.nsIRandomGenerator);
		return bytesToHex(generator.generateRandomBytes(32));
	}

	function getOrCreateProfileSecret() {
		let profileMaterial = Zotero.Prefs.get(SECRET_PREF);
		if (typeof profileMaterial === "string" && DIGEST_PATTERN.test(profileMaterial)) return profileMaterial;
		profileMaterial = randomProfileSecret();
		Zotero.Prefs.set(SECRET_PREF, profileMaterial);
		return profileMaterial;
	}

	async function writePrivateAuthenticationToken() {
		const directory = PathUtils.join(PathUtils.profileDir, AUTH_FOLDER);
		const path = PathUtils.join(directory, AUTH_TOKEN_FILE);
		await IOUtils.makeDirectory(directory, {
			createAncestors: true,
			ignoreExisting: true,
			permissions: 0o700,
		});
		await IOUtils.setPermissions(directory, 0o700, false);
		await IOUtils.writeUTF8(path, getAuthenticationToken(), { tmpPath: path + ".tmp" });
		await IOUtils.setPermissions(path, 0o600, false);
	}

	async function initializeZoteroRuntime(version) {
		const profileMaterial = getOrCreateProfileSecret();
		configureSecurity({
			getProfileSecret() { return profileMaterial; },
			sha256Hex: zoteroSHA256Hex,
			hmacSha256Hex: zoteroHMACSHA256Hex,
			now() { return Math.floor(Date.now() / 1000); },
		});
		configureRuntime({
			pluginVersion: version,
			zoteroVersion: Zotero.version,
			userLibraryID: Zotero.Libraries.userLibraryID,
			isInitialized() { return true; },
			async getAttachment(libraryID, key) {
				return Zotero.Items.getByLibraryAndKey(libraryID, key) || null;
			},
			generateKey() {
				return Zotero.DataObjectUtilities.generateKey();
			},
			executeTransaction(callback) {
				return Zotero.DB.executeTransaction(callback);
			},
			saveAnnotation(attachment, json) {
				return saveNativeAnnotationInTransaction(attachment, json);
			},
			eraseAnnotation(annotation) {
				return annotation.erase();
			},
		});
		await writePrivateAuthenticationToken();
		registerEndpoints(Zotero.Server);
	}

	async function saveNativeAnnotationInTransaction(attachment, json) {
		Zotero.DB.requireTransaction();
		let item = Zotero.Items.getByLibraryAndKey(attachment.libraryID, json.key);
		if (!item) {
			item = new Zotero.Item("annotation");
			item.libraryID = attachment.libraryID;
			item.key = json.key;
			await item.loadPrimaryData();
		}
		item.parentID = attachment.id;
		item._requireData("annotation");
		item._requireData("annotationDeferred");
		item.annotationType = json.type;
		item.annotationAuthorName = "";
		if (json.type === "highlight") item.annotationText = json.text || "";
		item.annotationIsExternal = false;
		item.annotationComment = json.comment;
		item.annotationColor = json.color;
		item.annotationPageLabel = json.pageLabel;
		item.annotationSortIndex = json.sortIndex;
		item.annotationPosition = JSON.stringify({ ...json.position });
		item.setTags((json.tags || []).map((tag) => ({ tag: tag.name })));
		await item.save({ skipSelect: true });
		return item;
	}

	function digestCanonical(value) {
		return requireSecurity().sha256Hex(canonicalJSONStringify(value));
	}

	function requestAuthenticationMessage(method, pathname, timestamp, body) {
		if (method !== "POST" || ![PREFLIGHT_PATH, APPLY_PATH].includes(pathname)) {
			throw protocolError(400, "invalid_auth_scope", "authentication scope is invalid");
		}
		assertInteger(timestamp, "authentication timestamp", 0);
		return [method, pathname, String(timestamp), digestCanonical(body)].join("\n");
	}

	function signRequestAuthentication(method, pathname, timestamp, body) {
		const message = requestAuthenticationMessage(method, pathname, timestamp, body);
		const signature = requireSecurity().hmacSha256Hex(getAuthenticationToken(), message);
		return String(timestamp) + "." + signature;
	}

	function verifyRequestAuthentication(value, method, pathname, body) {
		try {
			if (typeof value !== "string" || value.length > 96) return false;
			const parts = value.split(".");
			if (parts.length !== 2 || !/^[0-9]+$/.test(parts[0]) || !DIGEST_PATTERN.test(parts[1])) {
				return false;
			}
			const timestamp = Number(parts[0]);
			if (!Number.isSafeInteger(timestamp) || Math.abs(requireSecurity().now() - timestamp) > 30) {
				return false;
			}
			const expected = signRequestAuthentication(method, pathname, timestamp, body);
			return constantTimeEqual(expected, value);
		} catch (_) {
			return false;
		}
	}

	function configureRuntime(options) {
		assertAllowedKeys(
			options,
			[
				"pluginVersion", "zoteroVersion", "userLibraryID", "isInitialized", "getAttachment",
				"generateKey", "executeTransaction", "saveAnnotation", "eraseAnnotation",
			],
			"runtime options",
		);
		assertString(options.pluginVersion, "pluginVersion", 1, 64);
		assertString(options.zoteroVersion, "zoteroVersion", 1, 64);
		assertInteger(options.userLibraryID, "userLibraryID", 1);
		for (const name of ["isInitialized", "getAttachment"]) {
			if (typeof options[name] !== "function") {
				throw protocolError(500, "invalid_runtime", name + " runtime callback is required");
			}
		}
		for (const name of ["generateKey", "executeTransaction", "saveAnnotation", "eraseAnnotation"]) {
			if (options[name] !== undefined && typeof options[name] !== "function") {
				throw protocolError(500, "invalid_runtime", name + " must be a function");
			}
		}
		runtime = { ...options };
	}

	function requireRuntime() {
		if (!runtime || !runtime.isInitialized()) {
			throw protocolError(503, "not_initialized", "Zotero Local Bridge is not initialized");
		}
		return runtime;
	}

	function parseAnnotationPosition(value) {
		let position = value;
		if (typeof position === "string") {
			try {
				position = JSON.parse(position);
			} catch (_) {
				throw protocolError(500, "invalid_native_position", "native annotation position is invalid");
			}
		}
		assertObject(position, "native annotation position");
		return position;
	}

	function stableIDFromNative(annotation) {
		if (typeof annotation.stable_id === "string" && ID_PATTERN.test(annotation.stable_id)) {
			return annotation.stable_id;
		}
		if (typeof annotation.getTags === "function") {
			const match = annotation.getTags().find((entry) => {
				const tag = typeof entry === "string" ? entry : entry && entry.tag;
				return typeof tag === "string" && tag.startsWith(STABLE_TAG_PREFIX);
			});
			if (match) {
				const tag = typeof match === "string" ? match : match.tag;
				const stableID = tag.slice(STABLE_TAG_PREFIX.length);
				if (ID_PATTERN.test(stableID)) return stableID;
			}
		}
		return null;
	}

	function nativeState(annotation, attachmentKey) {
		const position = parseAnnotationPosition(annotation.annotationPosition);
		const stableID = stableIDFromNative(annotation);
		const state = {
			native_key: normalizeKey(annotation.key, "native annotation key"),
			stable_id: stableID,
			type: annotation.annotationType,
			page_index: position.pageIndex,
			page_label: typeof annotation.annotationPageLabel === "string"
				? annotation.annotationPageLabel
				: String(position.pageIndex + 1),
			sort_index: typeof annotation.annotationSortIndex === "string"
				? annotation.annotationSortIndex
				: defaultSortIndex(position.pageIndex, position),
			position,
			color: annotation.annotationColor,
			comment: annotation.annotationComment || "",
			text: annotation.annotationText || "",
		};
		Object.defineProperty(state, "_item", { value: annotation, enumerable: false });
		if (stableID) {
			state.fingerprint = annotationFingerprint(attachmentKey, {
				stable_id: stableID,
				type: state.type,
				page_index: state.page_index,
				page_label: state.page_label,
				sort_index: state.sort_index,
				position: state.position,
				color: state.color,
				comment: state.comment,
				...(state.type === "highlight" ? { text: state.text } : {}),
			});
		}
		return state;
	}

	function snapshotDigest(states) {
		const snapshot = states
			.map((state) => ({
				native_key: state.native_key,
				stable_id: state.stable_id,
				type: state.type,
				page_index: state.page_index,
				page_label: state.page_label,
				sort_index: state.sort_index,
				position: state.position,
				color: state.color,
				comment: state.comment,
				text: state.text,
			}))
			.sort((left, right) => left.native_key.localeCompare(right.native_key));
		return digestCanonical(snapshot);
	}

	function conciseActual(state) {
		return {
			native_key: state.native_key,
			stable_id: state.stable_id,
			type: state.type,
			page_index: state.page_index,
			page_label: state.page_label,
			sort_index: state.sort_index,
			position: state.position,
			color: state.color,
			comment: state.comment,
			fingerprint: state.fingerprint,
		};
	}

	async function readAttachmentState(request) {
		const currentRuntime = requireRuntime();
		if (request.library.id !== currentRuntime.userLibraryID) {
			throw protocolError(422, "user_library_required", "library id is not the active user library");
		}
		const attachment = await currentRuntime.getAttachment(
			request.library.id,
			request.attachment.key,
		);
		if (!attachment) {
			throw protocolError(404, "attachment_not_found", "PDF attachment was not found");
		}
		const isPDF = typeof attachment.isPDFAttachment === "function"
			? attachment.isPDFAttachment()
			: attachment.attachmentContentType === "application/pdf";
		if (attachment.libraryID !== currentRuntime.userLibraryID
				|| attachment.key !== request.attachment.key
				|| attachment.attachmentContentType !== "application/pdf"
				|| !isPDF) {
			throw protocolError(422, "pdf_required", "target must be the exact user-library PDF attachment");
		}
		if (typeof attachment.getAnnotations !== "function") {
			throw protocolError(500, "annotation_api_unavailable", "attachment annotation API is unavailable");
		}
		const nativeAnnotations = attachment.getAnnotations();
		if (!Array.isArray(nativeAnnotations)) {
			throw protocolError(500, "annotation_api_invalid", "attachment annotation API returned invalid data");
		}
		for (const annotation of nativeAnnotations) {
			if (typeof annotation.loadDataType === "function") {
				await annotation.loadDataType("tags");
			}
		}
		return {
			attachment,
			states: nativeAnnotations.map((annotation) => nativeState(annotation, attachment.key)),
		};
	}

	async function preflight(body) {
		const request = validateRequest(body, "preflight");
		const { attachment, states } = await readAttachmentState(request);
		const byKey = new Map(states.map((state) => [state.native_key, state]));
		const byStableID = new Map(states.filter((state) => state.stable_id).map((state) => [state.stable_id, state]));
		const counts = { create: 0, update: 0, delete: 0, no_op: 0 };
		const conflicts = [];
		const actual = [];
		const actions = [];
		const touchedKeys = new Set();

		for (const planned of request.annotations) {
			let existing = null;
			if (planned.native_key) {
				existing = byKey.get(planned.native_key);
				if (!existing) {
					throw protocolError(404, "native_key_not_found", "an update key was not found");
				}
				if (!existing.stable_id || existing.stable_id !== planned.stable_id) {
					conflicts.push({ code: "unknown_annotation", native_key: planned.native_key });
					continue;
				}
			} else {
				existing = byStableID.get(planned.stable_id) || null;
			}
			const desiredFingerprint = annotationFingerprint(attachment.key, planned);
			if (!existing) {
				counts.create += 1;
				actions.push({ kind: "create", planned });
				continue;
			}
			if (touchedKeys.has(existing.native_key)) {
				conflicts.push({ code: "duplicate_target", native_key: existing.native_key });
				continue;
			}
			touchedKeys.add(existing.native_key);
			actual.push(conciseActual(existing));
			if (existing.fingerprint === desiredFingerprint) {
				counts.no_op += 1;
				actions.push({ kind: "no_op", planned, existing });
			} else if (planned.native_key) {
				counts.update += 1;
				actions.push({ kind: "update", planned, existing });
			} else {
				conflicts.push({ code: "stable_id_collision", stable_id: planned.stable_id });
			}
		}

		for (const deletion of request.deletions) {
			const existing = byKey.get(deletion.native_key);
			if (!existing) {
				throw protocolError(404, "native_key_not_found", "a deletion key was not found");
			}
			if (touchedKeys.has(existing.native_key)) {
				conflicts.push({ code: "duplicate_target", native_key: existing.native_key });
				continue;
			}
			touchedKeys.add(existing.native_key);
			if (!existing.stable_id) {
				conflicts.push({ code: "unknown_annotation", native_key: existing.native_key });
				continue;
			}
			if (existing.fingerprint !== deletion.before_fingerprint) {
				conflicts.push({ code: "fingerprint_mismatch", native_key: existing.native_key });
				continue;
			}
			counts.delete += 1;
			actual.push(conciseActual(existing));
			actions.push({ kind: "delete", deletion, existing });
		}

		const planDigestValue = planDigest(request);
		const snapshotDigestValue = snapshotDigest(states);
		let receipt = null;
		if (conflicts.length === 0) {
			receipt = signReceipt({
				operation_id: request.operation_id,
				plan_digest: planDigestValue,
				snapshot_digest: snapshotDigestValue,
				expiry: requireSecurity().now() + 300,
				schema_version: SCHEMA_VERSION,
			});
		}
		const result = {
			plan_digest: planDigestValue,
			snapshot_digest: snapshotDigestValue,
			counts,
			conflicts,
			receipt,
			actual,
		};
		Object.defineProperties(result, {
			_actions: { value: actions, enumerable: false },
			_attachment: { value: attachment, enumerable: false },
		});
		return result;
	}

	function receiptPayloadFromReceipt(receipt) {
		if (typeof receipt !== "string") {
			throw protocolError(409, "invalid_receipt", "preflight receipt is invalid");
		}
		const parts = receipt.split(".");
		if (parts.length !== 2 || !DIGEST_PATTERN.test(parts[1])) {
			throw protocolError(409, "invalid_receipt", "preflight receipt is invalid");
		}
		try {
			return validateReceiptPayload(JSON.parse(hexToAscii(parts[0])));
		} catch (_) {
			throw protocolError(409, "invalid_receipt", "preflight receipt is invalid");
		}
	}

	function planFromApply(request) {
		return {
			schema_version: request.schema_version,
			operation_id: request.operation_id,
			library: request.library,
			attachment: request.attachment,
			annotations: request.annotations,
			allowed_native_keys: request.allowed_native_keys,
			deletions: request.deletions,
		};
	}

	function preservedTags(annotation, stableID) {
		const tags = annotation && typeof annotation.getTags === "function"
			? annotation.getTags().map((entry) => typeof entry === "string" ? entry : entry.tag)
			: [];
		const names = tags.filter((tag) => typeof tag === "string" && !tag.startsWith(STABLE_TAG_PREFIX));
		names.push(STABLE_TAG_PREFIX + stableID);
		return names.map((name) => ({ name }));
	}


	function nativeAnnotationJSON(planned, key, existingItem) {
		const json = {
			key,
			type: planned.type,
			comment: planned.comment,
			color: planned.color,
			pageLabel: planned.page_label,
			sortIndex: planned.sort_index,
			position: planned.position,
			tags: preservedTags(existingItem, planned.stable_id),
		};
		if (planned.type === "highlight") json.text = planned.text || "";
		return json;
	}

	function requireWriteRuntime() {
		const currentRuntime = requireRuntime();
		for (const name of ["generateKey", "executeTransaction", "saveAnnotation", "eraseAnnotation"]) {
			if (typeof currentRuntime[name] !== "function") {
				throw protocolError(503, "write_runtime_unavailable", "native write runtime is unavailable");
			}
		}
		return currentRuntime;
	}

	async function apply(body) {
		const request = validateRequest(body, "apply");
		const plan = planFromApply(request);
		const computedPlanDigest = planDigest(plan);
		if (computedPlanDigest !== request.plan_digest) {
			throw protocolError(409, "plan_digest_mismatch", "annotation plan changed after preflight");
		}
		const receiptPayload = receiptPayloadFromReceipt(request.receipt);
		if (receiptPayload.operation_id !== request.operation_id
				|| receiptPayload.plan_digest !== request.plan_digest
				|| receiptPayload.snapshot_digest !== request.snapshot_digest
				|| receiptPayload.schema_version !== request.schema_version
				|| !verifyReceipt(request.receipt, receiptPayload)) {
			throw protocolError(409, "invalid_receipt", "preflight receipt does not authorize this request");
		}

		const analysis = await preflight(plan);
		if (analysis.plan_digest !== request.plan_digest
				|| analysis.snapshot_digest !== request.snapshot_digest) {
			throw protocolError(409, "snapshot_changed", "attachment annotations changed after preflight");
		}
		if (analysis.conflicts.length) {
			throw protocolError(409, "preflight_conflict", "preflight conflicts must be resolved before apply");
		}
		const currentRuntime = requireWriteRuntime();
		return currentRuntime.executeTransaction(async () => {
			const locked = await readAttachmentState(plan);
			if (snapshotDigest(locked.states) !== request.snapshot_digest) {
				throw protocolError(409, "snapshot_changed", "attachment annotations changed before transaction");
			}
			const freshByKey = new Map(locked.states.map((state) => [state.native_key, state]));
			const readbackTargets = [];
			for (const action of analysis._actions) {
				if (action.kind === "create") {
					const key = normalizeKey(currentRuntime.generateKey(), "generated annotation key");
					if (freshByKey.has(key)) {
						throw protocolError(500, "generated_key_collision", "generated annotation key already exists");
					}
					const saved = await currentRuntime.saveAnnotation(
						locked.attachment,
						nativeAnnotationJSON(action.planned, key, null),
					);
					readbackTargets.push({ key: saved && saved.key ? saved.key : key, planned: action.planned });
				} else if (action.kind === "update") {
					const existing = freshByKey.get(action.existing.native_key);
					if (!existing) throw protocolError(409, "snapshot_changed", "update target disappeared");
					const saved = await currentRuntime.saveAnnotation(
						locked.attachment,
						nativeAnnotationJSON(action.planned, existing.native_key, existing._item),
					);
					readbackTargets.push({ key: saved && saved.key ? saved.key : existing.native_key, planned: action.planned });
				} else if (action.kind === "delete") {
					const existing = freshByKey.get(action.existing.native_key);
					if (!existing) throw protocolError(409, "snapshot_changed", "deletion target disappeared");
					await currentRuntime.eraseAnnotation(existing._item);
				} else if (action.kind === "no_op") {
					readbackTargets.push({ key: action.existing.native_key, planned: action.planned });
				}
			}

			const after = await readAttachmentState(plan);
			const afterByKey = new Map(after.states.map((state) => [state.native_key, state]));
			const actual = readbackTargets.map(({ key, planned }) => {
				const state = afterByKey.get(key);
				if (!state || state.fingerprint !== annotationFingerprint(after.attachment.key, planned)) {
					throw protocolError(500, "readback_mismatch", "native annotation readback did not match the plan");
				}
				return conciseActual(state);
			});
			return {
				counts: analysis.counts,
				native_keys: actual.map((state) => state.native_key),
				actual,
				snapshot_digest: snapshotDigest(after.states),
			};
		});
	}

	function jsonResponse(status, payload) {
		return [status, "application/json", JSON.stringify(payload)];
	}

	function errorResponse(error) {
		const status = Number.isInteger(error && error.status) ? error.status : 500;
		const code = typeof (error && error.code) === "string" ? error.code : "internal_error";
		const message = status === 500 ? "internal bridge error" : error.message;
		return jsonResponse(status, { error: { code, message } });
	}

	function validateAuthenticatedJSONRequest(request, expectedPath) {
		if (request.method !== "POST" || request.pathname !== expectedPath) {
			throw protocolError(400, "method_not_allowed", "endpoint supports its exact POST path only");
		}
		const headers = request.headers || {};
		if (headers.origin) {
			throw protocolError(403, "browser_origin_rejected", "browser Origin requests are rejected");
		}
		if (headers["content-type"] !== "application/json") {
			throw protocolError(400, "json_required", "Content-Type must be application/json");
		}
		if (!verifyRequestAuthentication(
			headers["x-zotero-local-bridge-auth"],
			request.method,
			request.pathname,
			request.data,
		)) {
			throw protocolError(401, "authentication_failed", "request authentication failed");
		}
	}

	function createEndpointClasses() {
		class HealthEndpoint {
			constructor() {
				this.supportedMethods = ["GET"];
			}

			init(request) {
				try {
					if (request.method !== "GET") {
						throw protocolError(400, "method_not_allowed", "health supports GET only");
					}
					if (request.headers && request.headers.origin) {
						throw protocolError(403, "browser_origin_rejected", "browser Origin requests are rejected");
					}
					const currentRuntime = requireRuntime();
					return jsonResponse(200, {
						plugin_version: currentRuntime.pluginVersion,
						zotero_version: currentRuntime.zoteroVersion,
						schema_version: SCHEMA_VERSION,
						supported_annotation_types: ["highlight", "image"],
						initialized: true,
					});
				} catch (error) {
					return errorResponse(error);
				}
			}
		}

		class PreflightEndpoint {
			constructor() {
				this.supportedMethods = ["POST"];
				this.supportedDataTypes = ["application/json"];
				this.allowRequestsFromUnsafeWebContent = false;
			}

			async init(request) {
				try {
					validateAuthenticatedJSONRequest(request, PREFLIGHT_PATH);
					const result = await preflight(request.data);
					return jsonResponse(result.conflicts.length ? 409 : 200, result);
				} catch (error) {
					return errorResponse(error);
				}
			}
		}

		class ApplyEndpoint {
			constructor() {
				this.supportedMethods = ["POST"];
				this.supportedDataTypes = ["application/json"];
				this.allowRequestsFromUnsafeWebContent = false;
			}

			async init(request) {
				try {
					validateAuthenticatedJSONRequest(request, APPLY_PATH);
					return jsonResponse(200, await apply(request.data));
				} catch (error) {
					return errorResponse(error);
				}
			}
		}

		return { HealthEndpoint, PreflightEndpoint, ApplyEndpoint };
	}

	function registerEndpoints(server) {
		if (!server || !isPlainObject(server.Endpoints)) {
			throw protocolError(500, "server_unavailable", "Zotero connector server is unavailable");
		}
		if (registeredServer) unregisterEndpoints();
		const endpointClasses = createEndpointClasses();
		if ([HEALTH_PATH, PREFLIGHT_PATH, APPLY_PATH].some((path) => server.Endpoints[path])) {
			throw protocolError(500, "endpoint_collision", "a Zotero Local Bridge endpoint already exists");
		}
		server.Endpoints[HEALTH_PATH] = endpointClasses.HealthEndpoint;
		server.Endpoints[PREFLIGHT_PATH] = endpointClasses.PreflightEndpoint;
		server.Endpoints[APPLY_PATH] = endpointClasses.ApplyEndpoint;
		registeredServer = server;
		registeredEndpoints = endpointClasses;
	}

	function unregisterEndpoints() {
		if (!registeredServer || !registeredEndpoints) return;
		const endpoints = [
			[HEALTH_PATH, "HealthEndpoint"],
			[PREFLIGHT_PATH, "PreflightEndpoint"],
			[APPLY_PATH, "ApplyEndpoint"],
		];
		for (const [path, name] of endpoints) {
			if (registeredServer.Endpoints[path] === registeredEndpoints[name]) {
				delete registeredServer.Endpoints[path];
			}
		}
		registeredServer = null;
		registeredEndpoints = null;
	}
	return {
		SCHEMA_VERSION,
		MAX_BATCH_SIZE,
		async init({ id, version, rootURI }) {
			this._plugin = { id, version, rootURI };
			await initializeZoteroRuntime(version);
		},
		shutdown() {
			unregisterEndpoints();
			this._plugin = null;
			runtime = null;
			security = null;
		},
		canonicalJSONStringify,
		configureSecurity,
		configureRuntime,
		registerEndpoints,
		unregisterEndpoints,
		preflight,
		apply,
		signRequestAuthentication,
		verifyRequestAuthentication,
		validateRequest,
		annotationFingerprint,
		planDigest,
		getAuthenticationToken,
		verifyAuthenticationToken,
		signReceipt,
		verifyReceipt,
	};
})();
