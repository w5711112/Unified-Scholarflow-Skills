# Security Policy

## Reporting

If you find a credential, private path, or other sensitive data that should not be public, open a private security advisory or contact the repository owner. Do not file a public issue that repeats the secret.

## Package contents

The repository contains skill rules, scripts, configuration examples with placeholder paths and IDs, and redacted screenshots.

## Browser bridge

The Edge native messaging host is registered under the current user (HKCU) only. Remove the registry key `NativeMessagingHosts\com.codex.searching_at_scale` to uninstall. The extension requests the smallest permission set needed for marketplace and search projection. It uses neither CDP nor WebDriver nor input injection.
