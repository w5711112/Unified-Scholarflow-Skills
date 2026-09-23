# Security Policy

## Reporting

If you find a credential, private path, or other sensitive data that should not be public, open a private security advisory or contact the repository owner. Do not file a public issue that repeats the secret.

## What this package intentionally does not ship

- Account passwords, API keys, tokens, or cookies
- Maintainer absolute machine paths, private vault names, or Zotero databases
- Unauthorized paper PDFs
- Modeling-contest working data

## Browser bridge

The Edge native messaging host is registered under the current user (HKCU) only. Remove the registry key `NativeMessagingHosts\com.codex.searching_at_scale` to uninstall. The extension requests the smallest permission set needed for marketplace/search projection and does not use CDP, WebDriver, or input injection.
