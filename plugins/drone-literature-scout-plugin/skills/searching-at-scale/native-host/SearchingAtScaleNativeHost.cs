using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Pipes;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;

internal static class SearchingAtScaleNativeHost
{
    private const string DefaultPipeName = "codex.searching_at_scale.v1";
    private const int ProtocolVersion = 3;
    private const int ProjectionSchemaVersion = 4;
    private const int MaxMessageBytes = 512 * 1024;
    private static readonly object StateLock = new object();
    private static readonly object OutputLock = new object();
    private static readonly JavaScriptSerializer Serializer = NewSerializer();
    private static readonly Regex TaskIdPattern = new Regex(
        "^[0-9a-f]{32}$",
        RegexOptions.CultureInvariant
    );
    private static readonly Regex PipeNamePattern = new Regex(
        "^[A-Za-z0-9._-]{1,128}$",
        RegexOptions.CultureInvariant
    );
    private static readonly Regex ProductIdPattern = new Regex(
        "^[0-9]+$",
        RegexOptions.CultureInvariant
    );
    private static readonly HashSet<string> TaskKeys = new HashSet<string>
    {
        "type", "protocol_version", "operation", "task_id", "platform",
        "query", "query_family", "cursor", "deadline_seconds", "max_items",
        "session_action", "pagination_enabled", "pagination_route"
    };
    private static readonly HashSet<string> TaskCursorKeys = new HashSet<string>
    {
        "cursor_id", "ordinal", "page_number"
    };
    private static readonly HashSet<string> ResultKeys = new HashSet<string>
    {
        "type", "protocol_version", "task_id", "payload"
    };
    private static readonly HashSet<string> ErrorKeys = new HashSet<string>
    {
        "type", "protocol_version", "task_id", "category", "retryable"
    };
    private static readonly HashSet<string> PayloadKeys = new HashSet<string>
    {
        "projection_schema_version", "capabilities", "platform", "page_state",
        "source_url", "query_family", "cursor", "observed_page_number",
        "pagination_state", "has_next_page", "sku_digest", "diagnostics", "items"
    };
    private static readonly HashSet<string> ResultCursorKeys = new HashSet<string>
    {
        "cursor_id", "page_number", "status"
    };
    private static readonly HashSet<string> DiagnosticKeys = new HashSet<string>
    {
        "document_ready_state", "data_sku_node_count", "candidate_anchor_count",
        "valid_item_count", "collection_elapsed_ms", "stable_rounds",
        "observed_page_number", "recovery_stage", "recovery_attempt", "source_path"
    };
    private static readonly HashSet<string> ItemKeys = new HashSet<string>
    {
        "product_id", "title", "url", "price", "shop", "commit", "good_rate",
        "promo", "stock", "image"
    };
    private static readonly string[] RequiredProjectionCapabilities = new string[]
    {
        "stable_card_fields_v2",
        "verified_pagination_v1",
        "resilient_pagination_v1"
    };
    private static readonly string[] CardFieldKeys = new string[]
    {
        "price", "shop", "commit", "good_rate", "promo", "stock", "image"
    };
    private static volatile bool Stopping;
    private static PendingTask Pending;

    private sealed class HostFailure : Exception
    {
        internal HostFailure(string category) { Category = category; }
        internal string Category { get; private set; }
    }

    private sealed class ValidTask
    {
        internal string TaskId;
        internal string Operation;
        internal string Platform;
        internal string QueryFamily;
        internal string CursorId;
        internal int PageNumber;
        internal int DeadlineMilliseconds;
    }

    private sealed class PendingTask
    {
        internal string TaskId;
        internal ValidTask Task;
        internal byte[] Response;
        internal readonly ManualResetEventSlim Done = new ManualResetEventSlim(false);
        internal readonly ManualResetEventSlim Finished = new ManualResetEventSlim(false);
    }

    private static JavaScriptSerializer NewSerializer()
    {
        var serializer = new JavaScriptSerializer();
        serializer.MaxJsonLength = MaxMessageBytes;
        serializer.RecursionLimit = 32;
        return serializer;
    }

    private static string PipeName()
    {
        string requested = Environment.GetEnvironmentVariable("SEARCHING_AT_SCALE_PIPE_NAME");
        if (String.IsNullOrEmpty(requested))
        {
            return DefaultPipeName;
        }
        if (!PipeNamePattern.IsMatch(requested))
        {
            throw new HostFailure("edge_native_pipe_name_invalid");
        }
        return requested;
    }

    private static PipeSecurity CurrentUserPipeSecurity()
    {
        SecurityIdentifier currentSid = WindowsIdentity.GetCurrent().User;
        if (currentSid == null)
        {
            throw new HostFailure("edge_native_pipe_acl_unavailable");
        }
        var security = new PipeSecurity();
        security.SetAccessRuleProtection(true, false);
        security.SetOwner(currentSid);
        security.AddAccessRule(new PipeAccessRule(
            currentSid,
            PipeAccessRights.FullControl,
            AccessControlType.Allow
        ));
        return security;
    }

    private static NamedPipeServerStream CreatePipeServer(string pipeName, PipeSecurity security)
    {
        return new NamedPipeServerStream(
            pipeName,
            PipeDirection.InOut,
            2,
            PipeTransmissionMode.Byte,
            PipeOptions.None,
            64 * 1024,
            64 * 1024,
            security
        );
    }

    private static bool HasExactKeys(
        IDictionary<string, object> value,
        HashSet<string> expected
    )
    {
        if (value == null || value.Count != expected.Count)
        {
            return false;
        }
        foreach (string key in value.Keys)
        {
            if (!expected.Contains(key))
            {
                return false;
            }
        }
        return true;
    }

    private static byte[] ReadFrame(Stream stream, bool allowCleanEof)
    {
        byte[] prefix = new byte[4];
        int first = stream.Read(prefix, 0, prefix.Length);
        if (first == 0 && allowCleanEof)
        {
            return null;
        }
        if (first <= 0)
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        ReadRemaining(stream, prefix, first);
        uint size = BitConverter.ToUInt32(prefix, 0);
        if (size == 0 || size > MaxMessageBytes)
        {
            throw new HostFailure("edge_native_message_too_large");
        }
        byte[] encoded = new byte[checked((int)size)];
        ReadRemaining(stream, encoded, 0);
        return encoded;
    }

    private static void ReadRemaining(Stream stream, byte[] buffer, int offset)
    {
        while (offset < buffer.Length)
        {
            int read = stream.Read(buffer, offset, buffer.Length - offset);
            if (read <= 0)
            {
                throw new HostFailure("edge_native_message_invalid");
            }
            offset += read;
        }
    }

    private static void WriteFrame(Stream stream, byte[] encoded)
    {
        if (encoded == null || encoded.Length == 0 || encoded.Length > MaxMessageBytes)
        {
            throw new HostFailure("edge_native_message_too_large");
        }
        byte[] prefix = BitConverter.GetBytes((uint)encoded.Length);
        stream.Write(prefix, 0, prefix.Length);
        stream.Write(encoded, 0, encoded.Length);
        stream.Flush();
    }

    private static Dictionary<string, object> DecodeObject(byte[] encoded)
    {
        string text;
        try
        {
            text = new UTF8Encoding(false, true).GetString(encoded);
            return Serializer.DeserializeObject(text) as Dictionary<string, object>;
        }
        catch
        {
            throw new HostFailure("edge_native_message_invalid");
        }
    }

    private static string RequiredText(
        IDictionary<string, object> root,
        string name,
        int maximum
    )
    {
        object value;
        string text;
        if (!root.TryGetValue(name, out value) || (text = value as string) == null)
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        text = text.Trim();
        if (text.Length == 0 || text.Length > maximum || text.IndexOf('\0') >= 0)
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        return text;
    }

    private static int RequiredInteger(
        IDictionary<string, object> root,
        string name,
        int minimum,
        int maximum
    )
    {
        object value;
        int number;
        if (!root.TryGetValue(name, out value) || !(value is int))
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        number = (int)value;
        if (number < minimum || number > maximum)
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        return number;
    }

    private static double RequiredNumber(
        IDictionary<string, object> root,
        string name,
        double minimumExclusive,
        double maximum
    )
    {
        object value;
        double number;
        if (!root.TryGetValue(name, out value))
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        if (value is int)
        {
            number = (int)value;
        }
        else if (value is decimal)
        {
            number = (double)(decimal)value;
        }
        else if (value is double)
        {
            number = (double)value;
        }
        else
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        if (Double.IsNaN(number) || Double.IsInfinity(number)
            || number <= minimumExclusive || number > maximum)
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        return number;
    }

    private static bool RequiredBoolean(IDictionary<string, object> root, string name)
    {
        object value;
        if (!root.TryGetValue(name, out value) || !(value is bool))
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        return (bool)value;
    }

    private static string RequiredResultText(
        IDictionary<string, object> root,
        string name,
        int maximum
    )
    {
        object value;
        string text;
        if (!root.TryGetValue(name, out value) || (text = value as string) == null)
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        text = text.Trim();
        if (text.Length == 0 || text.Length > maximum)
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        foreach (char character in text)
        {
            if (character < 0x20)
            {
                throw new HostFailure("edge_native_message_invalid");
            }
        }
        return text;
    }

    private static void ValidateNullableResultText(
        IDictionary<string, object> root,
        string name,
        int maximum
    )
    {
        object value;
        if (!root.TryGetValue(name, out value))
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        if (value == null)
        {
            return;
        }
        string text = value as string;
        if (text == null || text.Trim().Length == 0 || text.Trim().Length > maximum)
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        foreach (char character in text.Trim())
        {
            if (character < 0x20)
            {
                throw new HostFailure("edge_native_message_invalid");
            }
        }
    }

    private static bool IsOneOf(string value, params string[] allowed)
    {
        foreach (string candidate in allowed)
        {
            if (value == candidate)
            {
                return true;
            }
        }
        return false;
    }

    private static Uri RequiredSafeSourceUrl(
        IDictionary<string, object> payload,
        ValidTask task
    )
    {
        string text = RequiredResultText(payload, "source_url", 4096);
        Uri source;
        if (!Uri.TryCreate(text, UriKind.Absolute, out source)
            || source.Scheme != Uri.UriSchemeHttps
            || source.UserInfo.Length != 0
            || source.Query.Length != 0
            || source.Fragment.Length != 0)
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        string expectedHost = task.Platform == "jd" ? "search.jd.com" : "s.taobao.com";
        string expectedPath = task.Platform == "jd" ? "/Search" : "/search";
        if (!String.Equals(source.Host, expectedHost, StringComparison.OrdinalIgnoreCase)
            || source.AbsolutePath != expectedPath)
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        return source;
    }

    private static void ValidateItem(Dictionary<string, object> item, string platform)
    {
        if (!HasExactKeys(item, ItemKeys))
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        string productId = RequiredResultText(item, "product_id", 64);
        string title = RequiredResultText(item, "title", 1000);
        string urlText = RequiredResultText(item, "url", 2048);
        if (!ProductIdPattern.IsMatch(productId) || title.Length == 0)
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        foreach (string key in CardFieldKeys)
        {
            ValidateNullableResultText(item, key, 1024);
        }
        Uri url;
        if (!Uri.TryCreate(urlText, UriKind.Absolute, out url)
            || url.Scheme != Uri.UriSchemeHttps
            || url.UserInfo.Length != 0
            || url.Fragment.Length != 0)
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        if (platform == "jd")
        {
            if (!String.Equals(url.Host, "item.jd.com", StringComparison.OrdinalIgnoreCase)
                || url.AbsolutePath != "/" + productId + ".html"
                || url.Query.Length != 0)
            {
                throw new HostFailure("edge_native_message_invalid");
            }
            return;
        }
        bool allowedHost = IsOneOf(
            url.Host.ToLowerInvariant(),
            "item.taobao.com", "detail.tmall.com", "detail.tmall.hk"
        );
        if (!allowedHost
            || url.AbsolutePath != "/item.htm"
            || url.Query != "?id=" + productId)
        {
            throw new HostFailure("edge_native_message_invalid");
        }
    }

    private static void ValidateResultPayload(
        Dictionary<string, object> payload,
        ValidTask task
    )
    {
        if (!HasExactKeys(payload, PayloadKeys)
            || RequiredInteger(
                payload,
                "projection_schema_version",
                ProjectionSchemaVersion,
                ProjectionSchemaVersion
            ) != ProjectionSchemaVersion)
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        object capabilitiesValue;
        object[] capabilities;
        if (!payload.TryGetValue("capabilities", out capabilitiesValue)
            || (capabilities = capabilitiesValue as object[]) == null
            || capabilities.Length != RequiredProjectionCapabilities.Length)
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        for (int index = 0; index < RequiredProjectionCapabilities.Length; index += 1)
        {
            if ((capabilities[index] as string) != RequiredProjectionCapabilities[index])
            {
                throw new HostFailure("edge_native_message_invalid");
            }
        }
        if (RequiredResultText(payload, "platform", 16) != task.Platform
            || RequiredResultText(payload, "query_family", 512) != task.QueryFamily)
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        string pageState = RequiredResultText(payload, "page_state", 40);
        if (!IsOneOf(
            pageState,
            "ready", "authentication_required", "captcha_required",
            "page_structure_changed", "rate_limited"
        ))
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        RequiredSafeSourceUrl(payload, task);

        object cursorValue;
        Dictionary<string, object> cursor;
        if (!payload.TryGetValue("cursor", out cursorValue)
            || (cursor = cursorValue as Dictionary<string, object>) == null
            || !HasExactKeys(cursor, ResultCursorKeys)
            || RequiredResultText(cursor, "cursor_id", 512) != task.CursorId
            || RequiredInteger(cursor, "page_number", 1, 512) != task.PageNumber)
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        string cursorStatus = RequiredResultText(cursor, "status", 16);
        if (!IsOneOf(cursorStatus, "advanced", "exhausted", "stalled"))
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        int observedPage = RequiredInteger(payload, "observed_page_number", 1, 512);
        if (observedPage != task.PageNumber)
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        string paginationState = RequiredResultText(payload, "pagination_state", 32);
        if (!IsOneOf(
            paginationState,
            "pagination_unverified", "page_verified", "page_exhausted", "page_stalled"
        ))
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        RequiredBoolean(payload, "has_next_page");
        RequiredResultText(payload, "sku_digest", 4096);

        object diagnosticsValue;
        Dictionary<string, object> diagnostics;
        if (!payload.TryGetValue("diagnostics", out diagnosticsValue)
            || (diagnostics = diagnosticsValue as Dictionary<string, object>) == null
            || !HasExactKeys(diagnostics, DiagnosticKeys))
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        string readyState = RequiredResultText(diagnostics, "document_ready_state", 16);
        if (!IsOneOf(readyState, "loading", "interactive", "complete"))
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        RequiredInteger(diagnostics, "data_sku_node_count", 0, Int32.MaxValue);
        int candidateAnchorCount = RequiredInteger(
            diagnostics, "candidate_anchor_count", 0, Int32.MaxValue
        );
        int validItemCount = RequiredInteger(
            diagnostics, "valid_item_count", 0, Int32.MaxValue
        );
        RequiredInteger(diagnostics, "collection_elapsed_ms", 0, Int32.MaxValue);
        RequiredInteger(diagnostics, "stable_rounds", 0, Int32.MaxValue);
        int diagnosticPage = RequiredInteger(
            diagnostics, "observed_page_number", 1, 512
        );
        string recoveryStage = RequiredResultText(diagnostics, "recovery_stage", 16);
        if (diagnosticPage != task.PageNumber
            || diagnosticPage != observedPage
            || !IsOneOf(recoveryStage, "initial", "reproject", "reload")
            || RequiredInteger(diagnostics, "recovery_attempt", 0, 2) > 2
            || RequiredResultText(diagnostics, "source_path", 16) != "/Search")
        {
            throw new HostFailure("edge_native_message_invalid");
        }

        object itemsValue;
        object[] items;
        if (!payload.TryGetValue("items", out itemsValue)
            || (items = itemsValue as object[]) == null
            || items.Length > 1000
            || validItemCount != items.Length
            || candidateAnchorCount < validItemCount)
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        var seenProductIds = new HashSet<string>();
        foreach (object itemValue in items)
        {
            Dictionary<string, object> item = itemValue as Dictionary<string, object>;
            if (item == null)
            {
                throw new HostFailure("edge_native_message_invalid");
            }
            ValidateItem(item, task.Platform);
            string productId = (string)item["product_id"];
            if (!seenProductIds.Add(productId.Trim()))
            {
                throw new HostFailure("edge_native_message_invalid");
            }
        }
        string expectedStatus = pageState == "ready"
            ? items.Length > 0 ? "advanced" : "exhausted"
            : "stalled";
        if (cursorStatus != expectedStatus)
        {
            throw new HostFailure("edge_native_message_invalid");
        }
    }

    private static ValidTask ValidateTask(byte[] encoded)
    {
        Dictionary<string, object> root = DecodeObject(encoded);
        if (!HasExactKeys(root, TaskKeys)
            || RequiredText(root, "type", 16) != "task"
            || RequiredInteger(root, "protocol_version", 3, 3) != ProtocolVersion)
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        string taskId = RequiredText(root, "task_id", 32);
        if (!TaskIdPattern.IsMatch(taskId))
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        string operation = RequiredText(root, "operation", 16);
        string platform = RequiredText(root, "platform", 16);
        if (platform != "jd" && platform != "taobao")
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        RequiredText(root, "query", 512);
        string queryFamily = RequiredText(root, "query_family", 512);
        object cursorValue;
        Dictionary<string, object> cursor;
        if (!root.TryGetValue("cursor", out cursorValue)
            || (cursor = cursorValue as Dictionary<string, object>) == null
            || !HasExactKeys(cursor, TaskCursorKeys))
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        string cursorId = RequiredText(cursor, "cursor_id", 512);
        RequiredInteger(cursor, "ordinal", 0, 1000000);
        int pageNumber = RequiredInteger(cursor, "page_number", 1, 512);
        double deadline = RequiredNumber(root, "deadline_seconds", 0, 600);
        RequiredInteger(root, "max_items", 1, 1000);
        string sessionAction = RequiredText(root, "session_action", 16);
        bool paginationEnabled = RequiredBoolean(root, "pagination_enabled");
        if ((sessionAction != "start"
                && sessionAction != "next"
                && sessionAction != "recover")
            || (sessionAction == "start" && pageNumber != 1)
            || (sessionAction != "start" && !paginationEnabled)
            || (sessionAction == "next" && pageNumber <= 1)
            || (sessionAction == "recover" && platform != "jd"))
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        return new ValidTask
        {
            TaskId = taskId,
            Operation = operation,
            Platform = platform,
            QueryFamily = queryFamily,
            CursorId = cursorId,
            PageNumber = pageNumber,
            DeadlineMilliseconds = Math.Max(1000, checked((int)Math.Ceiling(deadline * 1000)))
        };
    }

    private static void ValidateExtensionEnvelope(byte[] encoded, PendingTask pending)
    {
        Dictionary<string, object> root = DecodeObject(encoded);
        string type = root == null ? null : root.ContainsKey("type") ? root["type"] as string : null;
        HashSet<string> keys = type == "result" ? ResultKeys : type == "error" ? ErrorKeys : null;
        if (keys == null || !HasExactKeys(root, keys)
            || RequiredInteger(root, "protocol_version", 3, 3) != ProtocolVersion
            || RequiredText(root, "task_id", 32) != pending.TaskId)
        {
            throw new HostFailure("edge_native_message_invalid");
        }
        if (type == "result")
        {
            object payloadValue;
            Dictionary<string, object> payload;
            if (!root.TryGetValue("payload", out payloadValue)
                || (payload = payloadValue as Dictionary<string, object>) == null)
            {
                throw new HostFailure("edge_native_message_invalid");
            }
            ValidateResultPayload(payload, pending.Task);
        }
        else
        {
            RequiredText(root, "category", 80);
            object retryable;
            if (!root.TryGetValue("retryable", out retryable) || !(retryable is bool))
            {
                throw new HostFailure("edge_native_message_invalid");
            }
        }
    }

    private static byte[] ErrorEnvelope(string taskId, string category, bool retryable)
    {
        var value = new Dictionary<string, object>
        {
            { "type", "error" },
            { "protocol_version", ProtocolVersion },
            { "task_id", taskId },
            { "category", category },
            { "retryable", retryable }
        };
        return Encoding.UTF8.GetBytes(Serializer.Serialize(value));
    }

    private static void WriteNativeTask(byte[] encoded)
    {
        lock (OutputLock)
        {
            WriteFrame(Console.OpenStandardOutput(), encoded);
        }
    }

    private static void HandlePipeClient(object state)
    {
        using (var pipe = (NamedPipeServerStream)state)
        {
            PendingTask pending = null;
            ValidTask task = null;
            try
            {
                byte[] encoded = ReadFrame(pipe, false);
                task = ValidateTask(encoded);
                if (task.Operation != "search")
                {
                    WriteFrame(pipe, ErrorEnvelope(
                        task.TaskId,
                        "edge_operation_unsupported",
                        false
                    ));
                    return;
                }
                lock (StateLock)
                {
                    if (Stopping)
                    {
                        WriteFrame(pipe, ErrorEnvelope(
                            task.TaskId,
                            "edge_background_bridge_disconnected",
                            true
                        ));
                        return;
                    }
                    if (Pending != null)
                    {
                        WriteFrame(pipe, ErrorEnvelope(
                            task.TaskId,
                            "edge_background_bridge_busy",
                            true
                        ));
                        return;
                    }
                    pending = new PendingTask { TaskId = task.TaskId, Task = task };
                    Pending = pending;
                }
                WriteNativeTask(encoded);
                if (!pending.Done.Wait(task.DeadlineMilliseconds + 2000))
                {
                    pending.Response = ErrorEnvelope(
                        task.TaskId,
                        "edge_extension_timeout",
                        true
                    );
                }
                WriteFrame(pipe, pending.Response ?? ErrorEnvelope(
                    task.TaskId,
                    "edge_background_bridge_disconnected",
                    true
                ));
            }
            catch (HostFailure failure)
            {
                string taskId = task == null ? new string('0', 32) : task.TaskId;
                try
                {
                    WriteFrame(pipe, ErrorEnvelope(taskId, failure.Category, false));
                }
                catch { }
            }
            catch
            {
                string taskId = task == null ? new string('0', 32) : task.TaskId;
                try
                {
                    WriteFrame(pipe, ErrorEnvelope(
                        taskId,
                        "edge_background_bridge_disconnected",
                        true
                    ));
                }
                catch { }
            }
            finally
            {
                if (pending != null)
                {
                    lock (StateLock)
                    {
                        if (Object.ReferenceEquals(Pending, pending))
                        {
                            Pending = null;
                        }
                    }
                    pending.Done.Dispose();
                    pending.Finished.Set();
                }
            }
        }
    }

    private static void PipeAcceptLoop(object state)
    {
        string pipeName = (string)state;
        PipeSecurity security;
        try
        {
            security = CurrentUserPipeSecurity();
        }
        catch
        {
            StopAll();
            return;
        }
        while (!Stopping)
        {
            NamedPipeServerStream server = null;
            try
            {
                server = CreatePipeServer(pipeName, security);
                server.WaitForConnection();
                if (Stopping)
                {
                    server.Dispose();
                    return;
                }
                ThreadPool.QueueUserWorkItem(HandlePipeClient, server);
                server = null;
            }
            catch
            {
                if (server != null)
                {
                    server.Dispose();
                }
                if (!Stopping)
                {
                    Thread.Sleep(20);
                }
            }
        }
    }

    private static void HandleNativeEnvelope(byte[] encoded)
    {
        PendingTask pending;
        lock (StateLock)
        {
            pending = Pending;
        }
        if (pending == null)
        {
            return;
        }
        try
        {
            ValidateExtensionEnvelope(encoded, pending);
            pending.Response = encoded;
        }
        catch (HostFailure failure)
        {
            pending.Response = ErrorEnvelope(pending.TaskId, failure.Category, false);
        }
        pending.Done.Set();
    }

    private static void StopAll()
    {
        Stopping = true;
        PendingTask pending;
        lock (StateLock)
        {
            pending = Pending;
            if (pending != null)
            {
                pending.Response = ErrorEnvelope(
                    pending.TaskId,
                    "edge_background_bridge_disconnected",
                    true
                );
                pending.Done.Set();
            }
        }
        if (pending != null)
        {
            pending.Finished.Wait(2000);
        }
    }

    private static int Main()
    {
        try
        {
            string pipeName = PipeName();
            var pipeThread = new Thread(PipeAcceptLoop);
            pipeThread.IsBackground = true;
            pipeThread.Name = "SearchingAtScalePipe";
            pipeThread.Start(pipeName);
            Stream input = Console.OpenStandardInput();
            while (!Stopping)
            {
                byte[] encoded = ReadFrame(input, true);
                if (encoded == null)
                {
                    break;
                }
                HandleNativeEnvelope(encoded);
            }
            StopAll();
            return 0;
        }
        catch
        {
            StopAll();
            return 2;
        }
    }
}
