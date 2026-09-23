from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import textwrap
import unittest
import zipfile
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_ROOT = PLUGIN_ROOT / "integrations" / "zotero-local-bridge"


class ZoteroLocalBridgeTests(unittest.TestCase):
    def test_isolated_reader_uses_the_in_process_fixture_probe(self):
        runner_path = (
            BRIDGE_ROOT / "tests" / "run_isolated_bridge_checks.py"
        )
        spec = importlib.util.spec_from_file_location(
            "zotero_local_bridge_isolated_runner",
            runner_path,
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        requested_urls: list[str] = []

        def fake_get_json(url: str):
            requested_urls.append(url)
            if url.endswith("/test/zotero-local-bridge/fixture"):
                return {
                    "ready": True,
                    "library_id": 37,
                    "attachment_key": "ABCD2345",
                    "annotations": [],
                }
            return []

        runner.get_json = fake_get_json
        self.assertEqual(
            runner.child_items("http://127.0.0.1:23120", 37, "ABCD2345"),
            [],
        )
        self.assertEqual(
            requested_urls,
            [
                "http://127.0.0.1:23120/test/zotero-local-bridge/fixture"
            ],
        )
    def test_local_bridge_keeps_upgrade_identity_and_loads_both_modules(self):
        manifest = json.loads(
            (BRIDGE_ROOT / "manifest.json").read_text(encoding="utf-8")
        )
        zotero = manifest["applications"]["zotero"]
        self.assertEqual(
            zotero["id"],
            "obsidian-link-bridge@read-paper-analysis-highlight.local",
        )
        self.assertTrue(manifest["version"].startswith("2."))
        bootstrap = (BRIDGE_ROOT / "bootstrap.js").read_text(encoding="utf-8")
        self.assertIn("loadSubScript(rootURI + \"link_bridge.js\")", bootstrap)
        self.assertIn("loadSubScript(rootURI + \"annotation_bridge.js\")", bootstrap)

    def test_manifest_targets_zotero_9(self):
        manifest = json.loads(
            (BRIDGE_ROOT / "manifest.json").read_text(encoding="utf-8")
        )
        zotero = manifest["applications"]["zotero"]
        self.assertEqual(zotero["strict_min_version"], "9.0")
        self.assertEqual(zotero["strict_max_version"], "9.0.*")

    def test_manifest_provides_required_fail_closed_https_update_url(self):
        manifest = json.loads(
            (BRIDGE_ROOT / "manifest.json").read_text(encoding="utf-8")
        )
        update_url = manifest["applications"]["zotero"]["update_url"]
        self.assertEqual(
            update_url,
            "https://obsidian-link.invalid/updates.json",
        )

    def test_bridge_fail_closes_to_reserved_origin_and_obsidian_open(self):
        source = (BRIDGE_ROOT / "link_bridge.js").read_text(encoding="utf-8")
        for required in (
            "https://obsidian-link.invalid",
            "obsidian:",
            'host !== "open"',
            "originalLoadURI",
            "launchObsidianURI",
            "launchWithURI",
            "removeFromAllWindows",
        ):
            with self.subTest(required=required):
                self.assertIn(required, source)
        self.assertNotIn("Zotero.launchURL", source)

    def test_valid_bridge_url_uses_system_handler_without_external_protocol_prompt(self):
        harness = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const calls = {
              launched: [],
              legacy: [],
              passthrough: [],
              errors: [],
            };
            const handler = {
              preferredAction: null,
              launchWithURI(uri) {
                calls.launched.push(uri.spec);
              },
            };
            const Ci = {
              nsIExternalProtocolService: Symbol("nsIExternalProtocolService"),
              nsIHandlerInfo: { useSystemDefault: 0 },
            };
            const context = {
              URL,
              Zotero: {
                getMainWindows() { return []; },
                logError(error) { calls.errors.push(String(error)); },
                launchURL(uri) { calls.legacy.push(uri); },
              },
              Services: {
                io: {
                  newURI(uri) { return { spec: uri }; },
                },
              },
              Components: {
                classes: {
                  "@mozilla.org/uriloader/external-protocol-service;1": {
                    getService(iface) {
                      if (iface !== Ci.nsIExternalProtocolService) {
                        throw new Error("unexpected interface");
                      }
                      return {
                        getProtocolHandlerInfo(scheme) {
                          if (scheme !== "obsidian") {
                            throw new Error("unexpected scheme");
                          }
                          return handler;
                        },
                      };
                    },
                  },
                },
                interfaces: Ci,
              },
            };

            vm.createContext(context);
            vm.runInContext(
              fs.readFileSync("link_bridge.js", "utf8"),
              context,
              { filename: "link_bridge.js" },
            );
            const pane = {
              loadURI(uris) { calls.passthrough.push(uris); },
            };
            context.ZoteroObsidianLinkBridge.addToWindow({ ZoteroPane: pane });
            const target =
              "obsidian://open?vault=Obsidian%20Vault&file=01-%E6%A0%B8%E5%BF%83%E8%AE%BA%E6%96%87%E7%B2%BE%E8%AF%BB%23%5Epaper-fixture";
            pane.loadURI(
              "https://obsidian-link.invalid/open?uri="
                + encodeURIComponent(target),
            );

            if (calls.launched.length !== 1 || calls.launched[0] !== target) {
              throw new Error("direct system handler was not used");
            }
            if (calls.legacy.length !== 0) {
              throw new Error("Zotero.launchURL would trigger the protocol prompt");
            }
            if (calls.passthrough.length !== 0) {
              throw new Error("allow-listed bridge URL leaked to normal browser handling");
            }
            """
        )
        result = subprocess.run(
            ["node", "-e", harness],
            cwd=BRIDGE_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            result.stdout + result.stderr,
        )

    def test_bootstrap_restores_wrapped_windows_on_shutdown(self):
        source = (BRIDGE_ROOT / "bootstrap.js").read_text(encoding="utf-8")
        for required in (
            "addToAllWindows",
            "onMainWindowLoad",
            "onMainWindowUnload",
            "removeFromAllWindows",
        ):
            with self.subTest(required=required):
                self.assertIn(required, source)

    def test_readme_guards_controlled_offline_upgrade(self):
        text = (BRIDGE_ROOT / "README.md").read_text(encoding="utf-8")
        required = (
            "离线原位升级",
            "Zotero 已完全停止",
            "bridge_click_verified",
            "plugin_installation_normalized",
            "行为门槛",
        )
        missing = [term for term in required if term not in text]
        self.assertFalse(missing, f"missing offline-upgrade guards: {missing}")


    def test_pure_protocol_rejects_unsafe_shapes_and_binds_receipts(self):
        harness = textwrap.dedent(
            r"""
            const crypto = require("crypto");
            const fs = require("fs");
            const vm = require("vm");

            const context = {};
            vm.createContext(context);
            vm.runInContext(
              fs.readFileSync("annotation_bridge.js", "utf8"),
              context,
              { filename: "annotation_bridge.js" },
            );
            const bridge = context.ZoteroNativeAnnotationBridge;
            bridge.configureSecurity({
              getProfileSecret() { return "11".repeat(32); },
              sha256Hex(value) {
                return crypto.createHash("sha256").update(value, "utf8").digest("hex");
              },
              hmacSha256Hex(key, value) {
                return crypto.createHmac("sha256", key).update(value, "utf8").digest("hex");
              },
              now() { return 1_000; },
            });

            const annotation = {
              stable_id: "paper-fixture-highlight-1",
              type: "highlight",
              page_index: 0,
              page_label: "4070",
              sort_index: "00000|000050|00000",
              position: { pageIndex: 0, rects: [[1, 2, 3, 4]] },
              color: "#ffd400",
              comment: "controlled comment",
            };
            const reorderedKeys = {
              comment: "controlled comment",
              color: "#ffd400",
              position: { rects: [[1, 2, 3, 4]], pageIndex: 0 },
              sort_index: "00000|000050|00000",
              page_label: "4070",
              page_index: 0,
              type: "highlight",
              stable_id: "paper-fixture-highlight-1",
            };
            const first = bridge.annotationFingerprint("ABCD2345", annotation);
            const reordered = bridge.annotationFingerprint("ABCD2345", reorderedKeys);
            if (first !== reordered) throw new Error("fingerprint is key-order dependent");
            if (!/^[a-f0-9]{64}$/.test(first)) throw new Error("fingerprint is not sha256");
            const changedPageLabel = bridge.annotationFingerprint(
              "ABCD2345",
              { ...annotation, page_label: "1" },
            );
            if (first === changedPageLabel) {
              throw new Error("fingerprint ignored the displayed page label");
            }
            const changedSortIndex = bridge.annotationFingerprint(
              "ABCD2345",
              { ...annotation, sort_index: "00000|000060|00000" },
            );
            if (first === changedSortIndex) {
              throw new Error("fingerprint ignored the native sort order");
            }

            const valid = {
              schema_version: 1,
              operation_id: "op-20260730-0001",
              library: { type: "user", id: 1 },
              attachment: { key: "ABCD2345", content_type: "application/pdf" },
              annotations: [annotation],
              allowed_native_keys: [],
              deletions: [],
            };
            const normalized = bridge.validateRequest(valid, "preflight");
            if (normalized.operation_id !== valid.operation_id) {
              throw new Error("valid request was not normalized");
            }

            function mustReject(mutator, label) {
              const candidate = JSON.parse(JSON.stringify(valid));
              mutator(candidate);
              let rejected = false;
              try { bridge.validateRequest(candidate, "preflight"); }
              catch (_) { rejected = true; }
              if (!rejected) throw new Error("accepted unsafe request: " + label);
            }
            mustReject(body => { body.library.type = "group"; }, "group library");
            mustReject(body => { body.attachment.content_type = "text/html"; }, "non-PDF");
            mustReject(body => { body.annotations[0].type = "note"; }, "annotation type");
            mustReject(body => { delete body.annotations[0].sort_index; }, "missing PDF sort index");
            mustReject(body => {
              body.annotations[0].sort_index = "00000|9999999000|0000001000";
            }, "non-native PDF sort index");
            mustReject(body => {
              body.annotations = Array.from({ length: 101 }, (_, i) => ({
                ...annotation,
                stable_id: "stable-" + i,
              }));
            }, "oversized batch");
            mustReject(body => { body.path = "C:\\arbitrary\\paper.pdf"; }, "arbitrary path");
            mustReject(body => { body.unexpected = true; }, "unknown top-level field");

            const receiptData = {
              operation_id: valid.operation_id,
              plan_digest: "a".repeat(64),
              snapshot_digest: "b".repeat(64),
              expiry: 1_300,
              schema_version: 1,
            };
            const receipt = bridge.signReceipt(receiptData);
            if (!bridge.verifyReceipt(receipt, receiptData)) {
              throw new Error("valid receipt was rejected");
            }
            const changedPlan = { ...receiptData, plan_digest: "c".repeat(64) };
            if (bridge.verifyReceipt(receipt, changedPlan)) {
              throw new Error("receipt accepted a changed plan");
            }
            if (bridge.getAuthenticationToken() === receipt.split(".")[1]) {
              throw new Error("authentication and receipt keys were not separated");
            }
            """
        )
        result = subprocess.run(
            ["node", "-e", harness],
            cwd=BRIDGE_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
    def test_bootstrap_awaits_native_endpoint_initialization(self):
        bootstrap = (BRIDGE_ROOT / "bootstrap.js").read_text(encoding="utf-8")
        annotation = (BRIDGE_ROOT / "annotation_bridge.js").read_text(encoding="utf-8")
        self.assertIn("await ZoteroNativeAnnotationBridge.init", bootstrap)
        for required in (
            "Zotero.Server",
            "Zotero.Items.getByLibraryAndKey",
            "IOUtils.setPermissions",
            "x-zotero-local-bridge-auth",
        ):
            with self.subTest(required=required):
                self.assertIn(required, annotation)
    def test_failure_harness_injects_the_native_item_save_path_only(self):
        source = (
            BRIDGE_ROOT / "tests" / "integration-harness" / "bootstrap.js"
        ).read_text(encoding="utf-8")
        self.assertNotIn("originalSaveFromJSON", source)
        self.assertIn("Zotero.Item.prototype.save", source)
        self.assertIn("this.isAnnotation()", source)
        self.assertIn("this.parentID === fixtureAttachment.id", source)
    def test_native_annotation_save_reuses_the_active_batch_transaction(self):
        source = (BRIDGE_ROOT / "annotation_bridge.js").read_text(encoding="utf-8")
        self.assertNotIn("Zotero.Annotations.saveFromJSON", source)
        self.assertIn("Zotero.DB.requireTransaction()", source)
        self.assertIn("await item.save({ skipSelect: true })", source)
        self.assertNotIn("item.saveTx(", source)
    def test_health_and_preflight_are_loopback_scoped_authenticated_and_read_only(self):
        harness = textwrap.dedent(
            r"""
            const crypto = require("crypto");
            const fs = require("fs");
            const vm = require("vm");

            (async () => {
              const context = {};
              vm.createContext(context);
              vm.runInContext(
                fs.readFileSync("annotation_bridge.js", "utf8"),
                context,
                { filename: "annotation_bridge.js" },
              );
              const bridge = context.ZoteroNativeAnnotationBridge;
              bridge.configureSecurity({
                getProfileSecret() { return "22".repeat(32); },
                sha256Hex(value) {
                  return crypto.createHash("sha256").update(value, "utf8").digest("hex");
                },
                hmacSha256Hex(key, value) {
                  return crypto.createHmac("sha256", key).update(value, "utf8").digest("hex");
                },
                now() { return 1_000; },
              });

              const annotations = [
                {
                  key: "ANN00001",
                  libraryID: 1,
                  parentKey: "ABCD2345",
                  stable_id: "controlled-existing",
                  annotationType: "highlight",
                  annotationPosition: JSON.stringify({ pageIndex: 0, rects: [[1, 2, 3, 4]] }),
                  annotationColor: "#ffd400",
                  annotationComment: "controlled comment",
                },
                {
                  key: "USER0001",
                  libraryID: 1,
                  parentKey: "ABCD2345",
                  annotationType: "highlight",
                  annotationPosition: JSON.stringify({ pageIndex: 1, rects: [[2, 3, 4, 5]] }),
                  annotationColor: "#ff6666",
                  annotationComment: "personal note that must not be returned",
                },
              ];
              const attachment = {
                key: "ABCD2345",
                libraryID: 1,
                attachmentContentType: "application/pdf",
                isPDFAttachment() { return true; },
                getAnnotations() { return annotations; },
              };
              const lookups = [];
              bridge.configureRuntime({
                pluginVersion: "2.0.0",
                zoteroVersion: "9.0.1",
                userLibraryID: 1,
                isInitialized() { return true; },
                async getAttachment(libraryID, key) {
                  lookups.push([libraryID, key]);
                  return libraryID === 1 && key === attachment.key ? attachment : null;
                },
              });

              const endpoints = {};
              bridge.registerEndpoints({ Endpoints: endpoints });
              const healthPath = "/zotero-local-bridge/v1/health";
              const preflightPath = "/zotero-local-bridge/v1/annotations/preflight";
              const applyPath = "/zotero-local-bridge/v1/annotations/apply";
              const paths = Object.keys(endpoints).sort();
              if (JSON.stringify(paths) !== JSON.stringify([healthPath, preflightPath, applyPath].sort())) {
                throw new Error("unexpected endpoint registration: " + JSON.stringify(paths));
              }

              const healthEndpoint = new endpoints[healthPath]();
              if (JSON.stringify(healthEndpoint.supportedMethods) !== JSON.stringify(["GET"])) {
                throw new Error("health method contract changed");
              }
              const healthResponse = await healthEndpoint.init({
                method: "GET", pathname: healthPath, headers: {}, data: null,
              });
              if (healthResponse[0] !== 200 || healthResponse[1] !== "application/json") {
                throw new Error("health endpoint failed");
              }
              const health = JSON.parse(healthResponse[2]);
              const healthKeys = Object.keys(health).sort();
              const expectedHealthKeys = [
                "initialized", "plugin_version", "schema_version",
                "supported_annotation_types", "zotero_version",
              ].sort();
              if (JSON.stringify(healthKeys) !== JSON.stringify(expectedHealthKeys)) {
                throw new Error("health leaked fields: " + JSON.stringify(healthKeys));
              }

              const planned = {
                stable_id: "controlled-new",
                type: "image",
                page_index: 2,
                page_label: "3",
                sort_index: "00002|000000|00020",
                position: { pageIndex: 2, rects: [[10, 20, 30, 40]] },
                color: "#2ea8e5",
                comment: "new controlled image",
              };
              const request = {
                schema_version: 1,
                operation_id: "op-preflight-additive",
                library: { type: "user", id: 1 },
                attachment: { key: "ABCD2345", content_type: "application/pdf" },
                annotations: [planned],
                allowed_native_keys: [],
                deletions: [],
              };
              const before = JSON.stringify(annotations);
              const preflightEndpoint = new endpoints[preflightPath]();
              if (JSON.stringify(preflightEndpoint.supportedMethods) !== JSON.stringify(["POST"])) {
                throw new Error("preflight method contract changed");
              }
              if (JSON.stringify(preflightEndpoint.supportedDataTypes) !== JSON.stringify(["application/json"])) {
                throw new Error("preflight content-type contract changed");
              }

              async function call(headers, body = request, method = "POST") {
                return preflightEndpoint.init({
                  method,
                  pathname: preflightPath,
                  headers,
                  data: body,
                });
              }
              const noAuth = await call({ "content-type": "application/json" });
              if (noAuth[0] !== 401) throw new Error("missing auth was accepted");
              const wrongType = await call({
                "content-type": "text/plain",
                "x-zotero-local-bridge-auth": "invalid",
              });
              if (wrongType[0] !== 400) throw new Error("non-JSON request was accepted");
              const origin = await call({
                origin: "https://example.invalid",
                "content-type": "application/json",
                "x-zotero-local-bridge-auth": "invalid",
              });
              if (origin[0] !== 403) throw new Error("Origin request was accepted");
              const options = await call({}, request, "OPTIONS");
              if (options[0] !== 400) throw new Error("OPTIONS was accepted by endpoint");

              const proof = bridge.signRequestAuthentication(
                "POST", preflightPath, 1_000, request,
              );
              const response = await call({
                "content-type": "application/json",
                "x-zotero-local-bridge-auth": proof,
              });
              if (response[0] !== 200) throw new Error("additive preflight failed: " + response[2]);
              const result = JSON.parse(response[2]);
              for (const field of [
                "plan_digest", "snapshot_digest", "counts", "conflicts", "receipt", "actual",
              ]) {
                if (!(field in result)) throw new Error("preflight omitted " + field);
              }
              if (result.counts.create !== 1 || result.counts.update !== 0
                  || result.counts.delete !== 0 || result.counts.no_op !== 0) {
                throw new Error("wrong additive counts: " + JSON.stringify(result.counts));
              }
              if (result.conflicts.length !== 0) throw new Error("user annotation blocked pure addition");
              if (response[2].includes("personal note")) throw new Error("unrelated comment leaked");
              if (JSON.stringify(annotations) !== before) throw new Error("preflight mutated fake store");
              if (JSON.stringify(lookups.at(-1)) !== JSON.stringify([1, "ABCD2345"])) {
                throw new Error("attachment was not looked up by exact library/key");
              }

              const destructive = JSON.parse(JSON.stringify(request));
              destructive.operation_id = "op-preflight-unknown-delete";
              destructive.annotations = [];
              destructive.allowed_native_keys = ["USER0001"];
              destructive.deletions = [{
                native_key: "USER0001",
                before_fingerprint: "d".repeat(64),
              }];
              const destructiveProof = bridge.signRequestAuthentication(
                "POST", preflightPath, 1_000, destructive,
              );
              const conflictResponse = await call({
                "content-type": "application/json",
                "x-zotero-local-bridge-auth": destructiveProof,
              }, destructive);
              if (conflictResponse[0] !== 409) {
                throw new Error("unknown destructive target was accepted");
              }
              const conflict = JSON.parse(conflictResponse[2]);
              if (!conflict.conflicts.some(item => item.code === "unknown_annotation")) {
                throw new Error("unknown annotation conflict was not concise/explicit");
              }
              if (JSON.stringify(annotations) !== before) throw new Error("conflict preflight mutated fake store");
            })().catch(error => {
              console.error(error.stack || error);
              process.exitCode = 1;
            });
            """
        )
        result = subprocess.run(
            ["node", "-e", harness],
            cwd=BRIDGE_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
    def test_atomic_apply_is_idempotent_snapshot_bound_and_rolls_back(self):
        harness = textwrap.dedent(
            r"""
            const crypto = require("crypto");
            const fs = require("fs");
            const vm = require("vm");

            (async () => {
              const context = {};
              vm.createContext(context);
              vm.runInContext(
                fs.readFileSync("annotation_bridge.js", "utf8"),
                context,
                { filename: "annotation_bridge.js" },
              );
              const bridge = context.ZoteroNativeAnnotationBridge;
              bridge.configureSecurity({
                getProfileSecret() { return "33".repeat(32); },
                sha256Hex(value) {
                  return crypto.createHash("sha256").update(value, "utf8").digest("hex");
                },
                hmacSha256Hex(key, value) {
                  return crypto.createHmac("sha256", key).update(value, "utf8").digest("hex");
                },
                now() { return 1_000; },
              });

              const stablePrefix = "zotero-local-bridge:stable-id:";
              function makeAnnotation(data) {
                const item = { ...data };
                item.loadDataType = async function () {};
                item.getTags = function () {
                  return (item.tags || []).map(tag => ({ tag }));
                };
                return item;
              }
              function raw(item) {
                return {
                  key: item.key,
                  libraryID: item.libraryID,
                  parentKey: item.parentKey,
                  annotationType: item.annotationType,
                  annotationPosition: item.annotationPosition,
                  annotationColor: item.annotationColor,
                  annotationComment: item.annotationComment,
                  annotationText: item.annotationText || "",
                  tags: [...(item.tags || [])],
                };
              }

              const annotations = [makeAnnotation({
                key: "USER0001",
                libraryID: 1,
                parentKey: "ABCD2345",
                annotationType: "highlight",
                annotationPosition: JSON.stringify({ pageIndex: 4, rects: [[2, 3, 4, 5]] }),
                annotationColor: "#ff6666",
                annotationComment: "personal untouched note",
                annotationText: "personal text",
                tags: ["personal-tag"],
              })];
              const originalUser = JSON.stringify(raw(annotations[0]));
              const attachment = {
                id: 99,
                key: "ABCD2345",
                libraryID: 1,
                attachmentContentType: "application/pdf",
                isPDFAttachment() { return true; },
                getAnnotations() { return annotations; },
              };

              let nextKey = 1;
              let failAtWrite = 0;
              let writes = 0;
              function maybeFail() {
                writes += 1;
                if (failAtWrite && writes === failAtWrite) {
                  throw new Error("injected write failure");
                }
              }
              function restore(snapshot) {
                annotations.splice(0, annotations.length, ...snapshot.map(makeAnnotation));
              }
              bridge.configureRuntime({
                pluginVersion: "2.0.0",
                zoteroVersion: "9.0.1",
                userLibraryID: 1,
                isInitialized() { return true; },
                async getAttachment(libraryID, key) {
                  return libraryID === 1 && key === attachment.key ? attachment : null;
                },
                generateKey() {
                  return "NEW" + String(nextKey++).padStart(5, "0");
                },
                async executeTransaction(callback) {
                  const snapshot = annotations.map(raw);
                  writes = 0;
                  try {
                    return await callback();
                  } catch (error) {
                    restore(snapshot);
                    throw error;
                  }
                },
                async saveAnnotation(_attachment, json) {
                  let item = annotations.find(candidate => candidate.key === json.key);
                  if (!item) {
                    item = makeAnnotation({ key: json.key, libraryID: 1, parentKey: "ABCD2345" });
                    annotations.push(item);
                  }
                  item.annotationType = json.type;
                  item.annotationPosition = JSON.stringify(json.position);
                  item.annotationColor = json.color;
                  item.annotationComment = json.comment;
                  item.annotationText = json.text || "";
                  item.tags = (json.tags || []).map(tag => tag.name);
                  maybeFail();
                  return item;
                },
                async eraseAnnotation(item) {
                  const index = annotations.findIndex(candidate => candidate.key === item.key);
                  if (index < 0) throw new Error("erase target missing");
                  annotations.splice(index, 1);
                  maybeFail();
                },
              });

              const endpoints = {};
              bridge.registerEndpoints({ Endpoints: endpoints });
              const preflightPath = "/zotero-local-bridge/v1/annotations/preflight";
              const applyPath = "/zotero-local-bridge/v1/annotations/apply";
              if (!endpoints[applyPath]) throw new Error("apply endpoint was not registered");
              const preflightEndpoint = new endpoints[preflightPath]();
              const applyEndpoint = new endpoints[applyPath]();
              if (JSON.stringify(applyEndpoint.supportedMethods) !== JSON.stringify(["POST"])) {
                throw new Error("apply method contract changed");
              }

              async function post(path, endpoint, body) {
                const proof = bridge.signRequestAuthentication("POST", path, 1_000, body);
                return endpoint.init({
                  method: "POST",
                  pathname: path,
                  headers: {
                    "content-type": "application/json",
                    "x-zotero-local-bridge-auth": proof,
                  },
                  data: body,
                });
              }
              async function preflight(plan) {
                const response = await post(preflightPath, preflightEndpoint, plan);
                if (response[0] !== 200) throw new Error("preflight failed: " + response[2]);
                return JSON.parse(response[2]);
              }
              async function applyPlan(plan, check) {
                const body = {
                  ...plan,
                  plan_digest: check.plan_digest,
                  snapshot_digest: check.snapshot_digest,
                  receipt: check.receipt,
                };
                return post(applyPath, applyEndpoint, body);
              }
              function annotation(stableID, comment, nativeKey) {
                const value = {
                  stable_id: stableID,
                  type: "highlight",
                  page_index: 0,
                  page_label: "1",
                  sort_index: "00000|000000|00002",
                  position: { pageIndex: 0, rects: [[1, 2, 3, 4]] },
                  color: "#ffd400",
                  comment,
                  text: "fixture highlighted text",
                };
                if (nativeKey) value.native_key = nativeKey;
                return value;
              }
              function plan(operationID, planned, allowed = [], deletions = []) {
                return {
                  schema_version: 1,
                  operation_id: operationID,
                  library: { type: "user", id: 1 },
                  attachment: { key: "ABCD2345", content_type: "application/pdf" },
                  annotations: planned,
                  allowed_native_keys: allowed,
                  deletions,
                };
              }

              const createPlan = plan("op-apply-create", [annotation("controlled-1", "created")]);
              const createCheck = await preflight(createPlan);
              const createResponse = await applyPlan(createPlan, createCheck);
              if (createResponse[0] !== 200) throw new Error("create apply failed: " + createResponse[2]);
              const created = JSON.parse(createResponse[2]);
              if (created.counts.create !== 1 || created.actual.length !== 1) {
                throw new Error("create readback mismatch");
              }
              const createdKey = created.actual[0].native_key;
              if (createdKey !== "NEW00001") throw new Error("unexpected created key");

              const duplicateCheck = await preflight(createPlan);
              if (duplicateCheck.counts.no_op !== 1) {
                throw new Error("response-loss reconciliation did not use full fingerprint");
              }
              const duplicateResponse = await applyPlan(createPlan, duplicateCheck);
              const duplicate = JSON.parse(duplicateResponse[2]);
              if (duplicateResponse[0] !== 200 || duplicate.counts.no_op !== 1
                  || duplicate.counts.create !== 0) {
                throw new Error("duplicate plan was not a no-op");
              }

              const updatePlan = plan(
                "op-apply-update",
                [annotation("controlled-1", "updated", createdKey)],
                [createdKey],
              );
              const updateCheck = await preflight(updatePlan);
              const updateResponse = await applyPlan(updatePlan, updateCheck);
              const updated = JSON.parse(updateResponse[2]);
              if (updateResponse[0] !== 200 || updated.counts.update !== 1
                  || updated.actual[0].comment !== "updated") {
                throw new Error("exact update failed");
              }

              const beforeFingerprint = bridge.annotationFingerprint(
                "ABCD2345", updatePlan.annotations[0],
              );
              const deletePlan = plan(
                "op-apply-delete",
                [],
                [createdKey],
                [{ native_key: createdKey, before_fingerprint: beforeFingerprint }],
              );
              const deleteCheck = await preflight(deletePlan);
              const deleteResponse = await applyPlan(deletePlan, deleteCheck);
              const deleted = JSON.parse(deleteResponse[2]);
              if (deleteResponse[0] !== 200 || deleted.counts.delete !== 1
                  || annotations.some(item => item.key === createdKey)) {
                throw new Error("exact delete failed");
              }

              const racePlan = plan("op-apply-race", [annotation("controlled-race", "race")]);
              const raceCheck = await preflight(racePlan);
              annotations.push(makeAnnotation({
                key: "USER0002",
                libraryID: 1,
                parentKey: "ABCD2345",
                annotationType: "image",
                annotationPosition: JSON.stringify({ pageIndex: 3, rects: [[3, 4, 5, 6]] }),
                annotationColor: "#aaaaaa",
                annotationComment: "concurrent manual annotation",
                tags: [],
              }));
              const raceResponse = await applyPlan(racePlan, raceCheck);
              if (raceResponse[0] !== 409
                  || annotations.some(item => item.tags?.includes(stablePrefix + "controlled-race"))) {
                throw new Error("changed snapshot was not fail-closed");
              }

              const rollbackPlan = plan("op-apply-rollback", [
                annotation("controlled-rollback-1", "first"),
                annotation("controlled-rollback-2", "second"),
              ]);
              const rollbackCheck = await preflight(rollbackPlan);
              const beforeRollback = JSON.stringify(annotations.map(raw));
              failAtWrite = 1;
              const rollbackResponse = await applyPlan(rollbackPlan, rollbackCheck);
              failAtWrite = 0;
              if (rollbackResponse[0] !== 500) throw new Error("injected failure was not reported");
              if (JSON.stringify(annotations.map(raw)) !== beforeRollback) {
                throw new Error("transaction rollback left visible residue");
              }
              if (JSON.stringify(raw(annotations.find(item => item.key === "USER0001"))) !== originalUser) {
                throw new Error("unknown user annotation changed");
              }
            })().catch(error => {
              console.error(error.stack || error);
              process.exitCode = 1;
            });
            """
        )
        result = subprocess.run(
            ["node", "-e", harness],
            cwd=BRIDGE_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
    def test_package_is_deterministic_minimal_and_isolation_scoped(self):
        script = BRIDGE_ROOT / "scripts" / "package_xpi.py"
        checklist_path = BRIDGE_ROOT / "tests" / "integration_checklist.json"
        self.assertTrue(script.is_file(), "deterministic packager is missing")
        self.assertTrue(checklist_path.is_file(), "isolation checklist is missing")

        case = PLUGIN_ROOT.parent / "运行数据" / "zotero-local-bridge-package-test"
        first = case / "first.xpi"
        second = case / "second.xpi"
        case.mkdir(parents=True, exist_ok=True)
        try:
            results = []
            for output in (first, second):
                result = subprocess.run(
                    ["python", str(script), "--output", str(output)],
                    cwd=BRIDGE_ROOT,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                results.append(json.loads(result.stdout))
            self.assertEqual(first.read_bytes(), second.read_bytes())
            digest = hashlib.sha256(first.read_bytes()).hexdigest()
            self.assertEqual(results[0]["sha256"], digest)
            self.assertEqual(results[1]["sha256"], digest)
            self.assertEqual(
                results[0]["plugin_id"],
                "obsidian-link-bridge@read-paper-analysis-highlight.local",
            )
            self.assertEqual(results[0]["version"], "2.3.0")

            with zipfile.ZipFile(first) as archive:
                self.assertEqual(
                    archive.namelist(),
                    [
                        "annotation_bridge.js",
                        "bootstrap.js",
                        "link_bridge.js",
                        "manifest.json",
                        "merge_bridge.js",
                    ],
                )
                for info in archive.infolist():
                    self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                packaged_manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual(packaged_manifest["version"], "2.3.0")
                self.assertEqual(
                    packaged_manifest["applications"]["zotero"]["id"],
                    "obsidian-link-bridge@read-paper-analysis-highlight.local",
                )
                self.assertFalse(any("auth-token" in name for name in archive.namelist()))
                self.assertFalse(any(name.endswith(".proxy") for name in archive.namelist()))

            checklist = json.loads(checklist_path.read_text(encoding="utf-8"))
            self.assertEqual(checklist["profile_scope"], "disposable")
            self.assertFalse(checklist["allow_live_profile"])
            self.assertFalse(checklist["allow_production_paper"])
            self.assertEqual(
                checklist["environment_guards"],
                {
                    "launch_mode": "headless",
                    "loopback_port_owner_count": 1,
                    "disable_word_processor_autoinstall": True,
                    "sort_index_pattern": r"^\d{5}\|\d{6}\|\d{5}$",
                },
            )
            self.assertEqual(
                checklist["required_checks"],
                [
                    "preflight_no_write",
                    "create_update_delete",
                    "duplicate_no_op",
                    "response_loss_reconciliation",
                    "rollback_injection",
                    "restart_health",
                    "obsidian_link_behavior",
                ],
            )
        finally:
            shutil.rmtree(case, ignore_errors=True)

if __name__ == "__main__":
    unittest.main()
